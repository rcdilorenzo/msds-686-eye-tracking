import os
import sys

# Setup visible GPUs
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]="1"

import tensorflow as tf
import keras.backend as K

# Configure tensorflow options
K.clear_session()
gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.9)
session = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))
K.set_session(session)

# Library imports
from funcy import compose, partial
from toolz.curried import *
from keras.optimizers import Adam
from keras.layers import *
from keras.layers.normalization import BatchNormalization
from keras.models import Model
from keras.callbacks import TensorBoard, ModelCheckpoint

# Import local files
from shared import capture_df, frame
from landmarks import landmarks
from generator import InspectorLestradeGenerator, SET_TYPE_TEST, SET_TYPE_TRAIN, SET_TYPE_VALIDATION


# ========================================
# Data and Scaling Transformations
# ========================================

# Filter for rows with landmarks
has_landmarks = lambda x: x.shape[0] > 0

# Create data frame and add landmarks as column
df = capture_df()
df['Landmarks'] = landmarks()

# Filter to only rows that have landmarks
df = df[df.Landmarks.apply(has_landmarks)]

# Data Format
#   Inputs:  [left_eyes, right_eyes, landmarks]
#   Outputs: [XCam, YCam] (centimeters relative position to lens)
BATCH_SIZE = 128
generator = InspectorLestradeGenerator(session, df, BATCH_SIZE, set_type=SET_TYPE_TRAIN)
val_generator = InspectorLestradeGenerator(session, df, BATCH_SIZE, set_type=SET_TYPE_VALIDATION)

# ========================================
# Loss Function
# ========================================

# (1/b) ∑^b_(i=1)([(^G-G)^2 + 1]^2 * [(^y - y)^2 + (^x - x)^2])
def loss_func(actual, pred):
    x_diff = tf.square(pred[:, 0] - actual[:, 0])
    y_diff = tf.square(pred[:, 1] - actual[:, 1])
    g_diff = tf.square(pred[:, 2] - actual[:, 2])

    return K.mean(tf.square(g_diff + 1) * (y_diff + x_diff))

# ========================================
# Callbacks
# ========================================

NAME = 'v13-v6-with-custom-activation'

board = TensorBoard(log_dir='./logs/' + NAME)

checkpoint = ModelCheckpoint('./models/' + NAME + '.{epoch:02d}-{val_loss:.2f}.hdf5',
                             monitor='val_loss')

# ========================================
# Model Layers
# ========================================

def coordinate_activation(x):
    return tf.pow(x, 3)

left_eye_input = Input(shape=(128,128,3))
right_eye_input = Input(shape=(128,128,3))
landmark_input = Input(shape=(68,3))

def eye_path(input_layer, prefix='na'):
    return pipe(
        input_layer,
        Conv2D(8, (3, 3), activation='relu', padding='same', name=(prefix + '_3x3conv1')),
        MaxPooling2D(pool_size=(3, 3), padding='same', name=(prefix + '_max1')),
        Conv2D(8, (3, 3), activation='relu', padding='same', name=(prefix + '_3x3conv2')),
        MaxPooling2D(pool_size=(3, 3), padding='same', name=(prefix + '_max2')),
        Conv2D(4, (2, 2), activation='relu', padding='same', name=(prefix + '_2x2conv1')),
        MaxPooling2D(pool_size=(2, 2), padding='same', name=(prefix + '_max3')),
        BatchNormalization(),
        Flatten(name=(prefix + '_flttn'))
    )


left_path = eye_path(left_eye_input, prefix='left')
right_path = eye_path(right_eye_input, prefix='right')

landmarks = pipe(
    landmark_input,
    Dense(16, activation='linear'),
    BatchNormalization(),
    Dense(8, activation='linear'),
    Flatten()
)

grouped = concatenate([left_path, right_path, landmarks])

coordinate = pipe(
    grouped,
    Dense(16, activation='linear'),
    Dense(8, activation='linear'),
    BatchNormalization(),
    Dense(2, activation=coordinate_activation, name='coord_output')
)

gaze_likelihood = pipe(
    grouped,
    Dense(8, activation='relu'),
    BatchNormalization(),
    Dense(4, activation='relu'),
    Dense(1, activation='sigmoid', name='gaze_likelihood')
)

output = pipe(
    concatenate([coordinate, gaze_likelihood]),
)

model = Model(inputs=[left_eye_input, right_eye_input, landmark_input],
              outputs=[output])

print('model', model.summary())

model.compile(optimizer=Adam(lr=1e1), loss=loss_func)

model.fit_generator(generator, validation_data=val_generator, steps_per_epoch=1000,
                    callbacks=[board, checkpoint], epochs=1000)

