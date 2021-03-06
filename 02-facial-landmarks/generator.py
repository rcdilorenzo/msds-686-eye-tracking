import os
import sys

# Import shared from directory above
sys.path.insert(0, '../')
from shared import frame, log

# Import local files
import facial_model as fm

# Library imports
from math import ceil
from toolz.curried import *
from funcy import compose
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.externals import joblib
from keras.utils.data_utils import Sequence

list_map = compose(list, map)

SET_TYPE_TRAIN = 'train'
SET_TYPE_TEST = 'test'
SET_TYPE_VALIDATION = 'val'


def find_or_create_scaler(data_frame):
    PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../architectures/scaler.pkl')
    )

    if os.path.exists(PATH):
        return joblib.load(PATH)

    scaler = StandardScaler(copy=True).fit(np.vstack(data_frame.Landmarks)[:, :])
    joblib.dump(scaler, PATH)
    return scaler

def scale_landmarks(scaler, landmarks_values):
    return np.array(list_map(scaler.transform, landmarks_values))


class InspectorLestradeGenerator(Sequence):
    def __init__(self, session, data_frame, batch_size, set_type=SET_TYPE_TRAIN, max_size=10000000):
        self.session = session
        self.data_frame = data_frame[data_frame.Dataset == set_type][0:max_size].sample(frac=1)
        self.batch_size = batch_size

        # Create scaler for facial features
        self.scaler = find_or_create_scaler(data_frame)

        # Import eyes tensorflow operations
        (predictions, image, factor, left_eye, right_eye,
         _l, _r, gaze_likelihood) = fm.eyes_tensor()

        self.predictions_input = predictions
        self.image_input = image
        self.factor_input = factor
        self.left_eye = left_eye
        self.right_eye = right_eye
        self.gaze_likelihood = gaze_likelihood

    def __len__(self):
        return ceil(self.data_frame.shape[0] / self.batch_size)

    def __rows_for(self, batch_id):
        start_index = batch_id * self.batch_size
        end_index = (batch_id + 1) * self.batch_size
        return self.data_frame.iloc[start_index:end_index]

    def __frames_for(self, rows):
        return rows.apply(frame, axis=1)

    def __reduce_eyes(self, acc, landmarks_and_image):
        eye_ops = (self.left_eye, self.right_eye, self.gaze_likelihood)
        (landmarks, image) = landmarks_and_image
        data = {
            self.predictions_input: landmarks,
            self.image_input: image,
            self.factor_input: 1.5
        }
        (left_eye, right_eye, likelihood) = self.session.run(eye_ops, feed_dict=data)
        return [acc[0] + [left_eye],
                acc[1] + [right_eye],
                acc[2] + [likelihood]]

    def __getitem__(self, batch_id):
        rows = self.__rows_for(batch_id)
        frames = self.__frames_for(rows)
        (left_eyes, right_eyes, likelihood) = reduce(
            self.__reduce_eyes,
            zip(np.stack(rows.Landmarks.apply(lambda r: r[:, 0:2]), 0), frames),
            ([], [], [])
        )
        landmarks = scale_landmarks(self.scaler, rows.Landmarks.values)
        output = np.column_stack(
            (rows['dotInfo.XCam'], rows['dotInfo.YCam'], likelihood)
        )
        return [np.array(left_eyes), np.array(right_eyes), landmarks], output
