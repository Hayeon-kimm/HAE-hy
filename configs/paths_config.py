dataset_paths = {
	'celeba_train': '',
	'celeba_test': '/local/rcs/ll3504/datasets/CelebAMask-HQ/CelebA-HQ-img',
	'celeba_train_sketch': '',
	'celeba_test_sketch': '',
	'celeba_train_segmentation': '',
	'celeba_test_segmentation': '',
	'ffhq': '/local/rcs/ll3504/datasets/FFHQ/resized',
	'flowers_train': '/home/rlagkdus705/datasets/flowers/train',
	'flowers_train_eva': '/proj/rcs-ssd/ll3504/datasets/flowers_eva/train',
	'flowers_valid': '/home/rlagkdus705/datasets/flowers/test',
	'flowers_test': '/proj/rcs-ssd/ll3504/datasets/flowers/test',
	'flowers_test_eva': '/proj/rcs-ssd/ll3504/datasets/flowers_eva/test',
	'animal_faces': '/proj/rcs-ssd/ll3504/datasets/animal_faces',
	'animal_faces_train_eva': '/proj/rcs-ssd/ll3504/datasets/animal_faces_eva/train',
	'animal_faces_test_eva': '/proj/rcs-ssd/ll3504/datasets/animal_faces_eva/test',
	'animal_faces_10': '/proj/rcs-ssd/ll3504/datasets/animal_faces_10_classes',
	'vgg_faces_train': '/proj/rcs-ssd/ll3504/datasets/vggfaces/train',
	'vgg_faces_test': '/proj/rcs-ssd/ll3504/datasets/vggfaces/test',
}

model_paths = {
	'stylegan_ffhq': '../params/stylegan2-ffhq-config-f.pt',
	'stylegan_flowers': '../params/stylegan2-flowers.pt',
	'stylegan_animalfaces': '../params/stylegan2-animalfaces.pt',
	'stylegan_vggfaces': '../params/psp_vggfaces.pt',
	'ir_se50': '../params/model_ir_se50.pth',
	'circular_face': '../params/CurricularFace_Backbone.pth',
	'mtcnn_pnet': '../params/mtcnn/pnet.npy',
	'mtcnn_rnet': '../params/mtcnn/rnet.npy',
	'mtcnn_onet': '../params/mtcnn/onet.npy',
	'shape_predictor': 'shape_predictor_68_face_landmarks.dat',
	'moco': '../params/moco_v2_800ep_pretrain.pth.tar'
}
