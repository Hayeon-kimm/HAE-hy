import scipy.io
import os
import shutil
import random

# mat 파일 경로
mat_file_path = '/home/rlagkdus705/datasets/flowers/imagelabels.mat'
images_dir = '/home/rlagkdus705/datasets/flowers'
train_dir = '/home/rlagkdus705/datasets/flowers/train/'
test_dir = '/home/rlagkdus705/datasets/flowers/test/'

# mat 파일 읽기
mat_data = scipy.io.loadmat(mat_file_path)
labels = mat_data['labels'][0]

# label을 고유값으로 변환 후 셔플
unique_labels = list(set(labels))
random.shuffle(unique_labels)

# 85개와 17개로 나누기
train_labels = unique_labels[:85]
test_labels = unique_labels[85:]

# label에 해당하는 이미지들을 저장할 딕셔너리
label_img = {}

# label에 해당하는 이미지 매칭
def match_label_image():
    for idx, label in enumerate(labels):
        if label in label_img:
            label_img[label].append(f'image_{str(idx + 1).zfill(5)}.jpg')
        else:
            label_img[label] = [f'image_{str(idx + 1).zfill(5)}.jpg']

match_label_image()

# 이미지 파일 복사 함수
def copy_images(label_list, base_dir):
    for label in label_list:
        label_dir = os.path.join(base_dir, str(label))
        os.makedirs(label_dir, exist_ok=True)
        if label in label_img:
            for img_file in label_img[label]:
                src_path = os.path.join(images_dir, img_file)
                dst_path = os.path.join(label_dir, img_file)
                if os.path.exists(src_path):
                    shutil.copy(src_path, dst_path)

# 이미지 복사
copy_images(train_labels, train_dir)
copy_images(test_labels, test_dir)

print(f'Train images copied to {train_dir}')
print(f'Test images copied to {test_dir}')
