import os
import matplotlib
import matplotlib.pyplot as plt

matplotlib.use('Agg')

import torch
from torch import nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
import torch.nn.functional as F
from utils import common, train_utils
from criteria import id_loss, w_norm, moco_loss, contrastive_loss
from configs import data_configs
from datasets.images_dataset import ImagesDataset
from criteria.lpips.lpips import LPIPS
from models.hae_hy import hae
from training.ranger import Ranger


class Coach:
	def __init__(self, opts):
		self.opts = opts
		self.global_step = 0
		torch.cuda.set_device(0)
		self.device = 'cuda'  # TODO: Allow multiple GPU? currently using CUDA_VISIBLE_DEVICES
		self.opts.device = self.device

		if self.opts.use_wandb:
			from utils.wandb_utils import WBLogger
			self.wb_logger = WBLogger(self.opts)

		# Initialize network
		self.net = hae(self.opts).to(self.device)

		# Estimate latent_avg via dense sampling if latent_avg is not available
		if self.net.latent_avg is None:
			self.net.latent_avg = self.net.decoder.mean_latent(int(1e5))[0].detach()

		# Initialize loss
		if self.opts.id_lambda > 0 and self.opts.moco_lambda > 0:
			raise ValueError('Both ID and MoCo loss have lambdas > 0! Please select only one to have non-zero lambda!')
		self.mse_loss = nn.MSELoss().to(self.device).eval()
		if self.opts.lpips_lambda > 0:
			self.lpips_loss = LPIPS(net_type='alex', device=self.device).to(self.device).eval()
		if self.opts.id_lambda > 0:
			self.id_loss = id_loss.IDLoss().to(self.device).eval()
		if self.opts.w_norm_lambda > 0:
			self.w_norm_loss = w_norm.WNormLoss(start_from_latent_avg=self.opts.start_from_latent_avg)
		if self.opts.moco_lambda > 0:
			self.moco_loss = moco_loss.MocoLoss().to(self.device).eval()
		if self.opts.contrastive_lambda > 0:
			self.contrastive_loss = contrastive_loss.SupConLoss().to(self.device).eval()

		# Initialize optimizer
		self.optimizer = self.configure_optimizers()

		# Initialize dataset
		self.train_dataset, self.test_dataset = self.configure_datasets()
		self.train_dataloader = DataLoader(self.train_dataset,
										   batch_size=self.opts.batch_size,
										   shuffle=True,
										   num_workers=int(self.opts.workers),
										   drop_last=True)
		self.test_dataloader = DataLoader(self.test_dataset,
										  batch_size=self.opts.test_batch_size,
										  shuffle=False,
										  num_workers=int(self.opts.test_workers),
										  drop_last=True)

		# Initialize logger
		log_dir = os.path.join(opts.exp_dir, 'logs')
		os.makedirs(log_dir, exist_ok=True)
		self.logger = SummaryWriter(log_dir=log_dir)

		# Initialize checkpoint dir
		self.checkpoint_dir = os.path.join(opts.exp_dir, 'checkpoints')
		os.makedirs(self.checkpoint_dir, exist_ok=True)
		self.best_val_loss = None
		if self.opts.save_interval is None:
			self.opts.save_interval = self.opts.max_steps

	def train(self):
		self.net.train()
		while self.global_step < self.opts.max_steps:
			correct = 0
			data_size = 0
			for batch_idx, batch in enumerate(self.train_dataloader):
				self.optimizer.zero_grad()
				x, y, label = batch
				x, y, label = x.to(self.device).float(), y.to(self.device).float(), label.to(self.device)
				#images = torch.cat([x, z], dim=0)
				images = x
				bsz = label.shape[0]
				data_size += bsz
				y_hat, latent, logits, feature_dist, ocodes, feature_euc = self.net.forward(images, batch_size=bsz, return_latents=True)
				loss, loss_dict, id_logs = self.calc_loss(x, y, y_hat, latent, logits, label, ocodes, feature_euc)
				pred = logits.argmax(dim=1, keepdim=True)
				correct += pred.eq(label.view_as(pred)).sum().item()
				loss.backward()
				self.optimizer.step()

				# Logging related
				if self.global_step % self.opts.image_interval == 0 or (self.global_step < 1000 and self.global_step % 25 == 0):
					self.parse_and_log_images(id_logs, x, y, y_hat, title='images/train/faces')
				if self.global_step % self.opts.board_interval == 0:
					self.print_metrics(loss_dict, prefix='train')
					self.log_metrics(loss_dict, prefix='train')
					if self.global_step != 0 and data_size != 0:
						print("Test set: Accuracy: {}/{} ({:.0f}%)\n".format(correct, data_size, 100.0*correct/data_size))
						correct = 0
						data_size = 0

				# Log images of first batch to wandb
				if self.opts.use_wandb and batch_idx == 0:
					self.wb_logger.log_images_to_wandb(x, y, y_hat, id_logs, prefix="train", step=self.global_step, opts=self.opts)

				# Validation related
				val_loss_dict = None
				if self.global_step % self.opts.val_interval == 0 or self.global_step == self.opts.max_steps:
					val_loss_dict = self.validate()
					if val_loss_dict and (self.best_val_loss is None or val_loss_dict['loss'] < self.best_val_loss):
						self.best_val_loss = val_loss_dict['loss']
						self.checkpoint_me(val_loss_dict, is_best=True)

				if self.global_step % self.opts.save_interval == 0 or self.global_step == self.opts.max_steps:
					if val_loss_dict is not None:
						self.checkpoint_me(val_loss_dict, is_best=False)
					else:
						self.checkpoint_me(loss_dict, is_best=False)

				if self.global_step == self.opts.max_steps:
					print('OMG, finished training!')
					break

				self.global_step += 1

	def validate(self):
		self.net.eval()
		agg_loss_dict = []
		correct = 0
		for batch_idx, batch in enumerate(self.test_dataloader):
			x, y, label = batch

			with torch.no_grad():
				x, y, label = x.to(self.device).float(), y.to(self.device).float(), label.to(self.device)
				#images = torch.cat([x, z], dim=0)
				images = x
				bsz = label.shape[0]
				y_hat, latent, logits, feature_dist, ocodes, feature_euc = self.net.forward(images, batch_size=bsz, return_latents=True)
				loss, cur_loss_dict, id_logs = self.calc_loss(x, y, y_hat, latent, logits, label, ocodes, feature_euc)
				pred = logits.argmax(dim=1, keepdim=True)
				correct += pred.eq(label.view_as(pred)).sum().item()
			agg_loss_dict.append(cur_loss_dict)

			# Logging related
			self.parse_and_log_images(id_logs, x, y, y_hat,
									  title='images/test/faces',
									  subscript='{:04d}'.format(batch_idx))

			# Log images of first batch to wandb
			if self.opts.use_wandb and batch_idx == 0:
				self.wb_logger.log_images_to_wandb(x, y, y_hat, id_logs, prefix="test", step=self.global_step, opts=self.opts)

			# For first step just do sanity test on small amount of data
			if self.global_step == 0 and batch_idx >= 4:
				self.net.train()
				return None  # Do not log, inaccurate in first batch

		loss_dict = train_utils.aggregate_loss_dict(agg_loss_dict)
		self.log_metrics(loss_dict, prefix='test')
		self.print_metrics(loss_dict, prefix='test')
		print("\nTest set: Accuracy: {}/{} ({:.0f}%)\n".format(correct, len(self.test_dataloader.dataset), 100.0*correct/len(self.test_dataloader.dataset)))

		self.net.train()
		return loss_dict

	def checkpoint_me(self, loss_dict, is_best):
		save_name = 'best_model.pt' if is_best else f'iteration_{self.global_step}.pt'
		save_dict = self.__get_save_dict()
		checkpoint_path = os.path.join(self.checkpoint_dir, save_name)
		torch.save(save_dict, checkpoint_path)
		with open(os.path.join(self.checkpoint_dir, 'timestamp.txt'), 'a') as f:
			if is_best:
				f.write(f'**Best**: Step - {self.global_step}, Loss - {self.best_val_loss} \n{loss_dict}\n')
				if self.opts.use_wandb:
					self.wb_logger.log_best_model()
			else:
				f.write(f'Step - {self.global_step}, \n{loss_dict}\n')

	def configure_optimizers(self):
		params = list(self.net.mlp_encoder.parameters())
		params += list(self.net.mlp_decoder.parameters())
		params += list(self.net.hyperbolic_linear.parameters())
		params += list(self.net.mlr.parameters())
		if self.opts.optim_name == 'adam':
			optimizer = torch.optim.Adam(params, lr=self.opts.learning_rate)
		else:
			optimizer = Ranger(params, lr=self.opts.learning_rate)
		return optimizer

	def configure_datasets(self):
		if self.opts.dataset_type not in data_configs.DATASETS.keys():
			Exception(f'{self.opts.dataset_type} is not a valid dataset_type')
		print(f'Loading dataset for {self.opts.dataset_type}')
		dataset_args = data_configs.DATASETS[self.opts.dataset_type]
		transforms_dict = dataset_args['transforms'](self.opts).get_transforms()
		#print(transforms_dict)
		train_dataset = ImagesDataset(source_root=dataset_args['train_source_root'],
									  target_root=dataset_args['train_target_root'],
									  source_transform=transforms_dict['transform_source'],
									  target_transform=transforms_dict['transform_gt_train'],
									  train_transform=transforms_dict['transform_train'],
									  opts=self.opts)
		test_dataset = ImagesDataset(source_root=dataset_args['test_source_root'],
									 target_root=dataset_args['test_target_root'],
									 source_transform=transforms_dict['transform_source'],
									 target_transform=transforms_dict['transform_test'],
									 opts=self.opts)
		if self.opts.use_wandb:
			self.wb_logger.log_dataset_wandb(train_dataset, dataset_name="Train")
			self.wb_logger.log_dataset_wandb(test_dataset, dataset_name="Test")
		print(f"Number of training samples: {len(train_dataset)}")
		print(f"Number of test samples: {len(test_dataset)}")
		return train_dataset, test_dataset

	def calc_loss(self, x, y, y_hat, latent, logits, label, ocodes, feature_euc):
		loss_dict = {}
		loss = 0.0
		id_logs = None
		if self.opts.l2_lambda > 0:
			loss_l2 = F.mse_loss(y_hat, y)
			loss_dict['loss_l2'] = float(loss_l2)
			loss += loss_l2 * self.opts.l2_lambda
		if self.opts.lpips_lambda > 0:
			loss_lpips = self.lpips_loss(y_hat, y)
			loss_dict['loss_lpips'] = float(loss_lpips)
			loss += loss_lpips * self.opts.lpips_lambda
		if self.opts.hyperbolic_lambda > 0:
			loss_hyperbolic = F.nll_loss(logits, label)
			loss_dict['loss_hyperbolic'] = float(loss_hyperbolic)
			loss += loss_hyperbolic * self.opts.hyperbolic_lambda
		if self.opts.reverse_lambda > 0:
			loss_reverse = F.mse_loss(ocodes, feature_euc)
			if float(loss_reverse) <= 0.2 and float(loss_reverse) > 0.1:
				reverse_lambda = 3
			elif float(loss_reverse) <= 0.1 and float(loss_reverse) > 0.05:
				reverse_lambda = 6
			elif float(loss_reverse) <= 0.05 and float(loss_reverse) > 0.025:
				reverse_lambda = 12
			elif float(loss_reverse) <= 0.025 and float(loss_reverse) > 0.0125:
				reverse_lambda = 24
			elif float(loss_reverse) <= 0.0125 and float(loss_reverse) > 0.00625:
				reverse_lambda = 48
			elif float(loss_reverse) <= 0.00625 and float(loss_reverse) > 0.003125:
				reverse_lambda = 96
			elif float(loss_reverse) <= 0.003125:
				reverse_lambda = 150
			else:
				reverse_lambda = self.opts.reverse_lambda
			loss_dict['loss_reverse'] = float(loss_reverse)
			loss += loss_reverse * reverse_lambda
		'''
		if self.opts.contrastive_lambda > 0:
			loss_contrastive = self.contrastive_loss(feature_dist)
			loss_dict['info_nce'] = float(loss_contrastive)
			loss += loss_contrastive * self.opts.contrastive_lambda
		'''

		loss_dict['loss'] = float(loss)
		return loss, loss_dict, id_logs

	def log_metrics(self, metrics_dict, prefix):
		for key, value in metrics_dict.items():
			self.logger.add_scalar(f'{prefix}/{key}', value, self.global_step)
		if self.opts.use_wandb:
			self.wb_logger.log(prefix, metrics_dict, self.global_step)

	def print_metrics(self, metrics_dict, prefix):
		print(f'Metrics for {prefix}, step {self.global_step}')
		for key, value in metrics_dict.items():
			print(f'\t{key} = ', value)

	def parse_and_log_images(self, id_logs, x, y, y_hat, title, subscript=None, display_count=2):
		im_data = []
		for i in range(display_count):
			cur_im_data = {
				'input_face': common.log_input_image(x[i], self.opts),
				'target_face': common.tensor2im(y[i]),
				'output_face': common.tensor2im(y_hat[i]),
			}
			if id_logs is not None:
				for key in id_logs[i]:
					cur_im_data[key] = id_logs[i][key]
			im_data.append(cur_im_data)
		self.log_images(title, im_data=im_data, subscript=subscript)

	def log_images(self, name, im_data, subscript=None, log_latest=False):
		fig = common.vis_faces(im_data)
		step = self.global_step
		if log_latest:
			step = 0
		if subscript:
			path = os.path.join(self.logger.log_dir, name, f'{subscript}_{step:04d}.jpg')
		else:
			path = os.path.join(self.logger.log_dir, name, f'{step:04d}.jpg')
		os.makedirs(os.path.dirname(path), exist_ok=True)
		fig.savefig(path)
		plt.close(fig)

	def __get_save_dict(self):
		save_dict = {
			'state_dict': self.net.state_dict(),
			'opts': vars(self.opts)
		}
		# save the latent avg in state_dict for inference if truncation of w was used during training
		if self.opts.start_from_latent_avg:
			save_dict['latent_avg'] = self.net.latent_avg
		return save_dict
