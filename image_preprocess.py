import cv2
import numpy as np


def process(img, coordinates):

    x, y, w, h = map(int, coordinates)

    cropped_img = img[y:h, x:w]

    # upscale the crop so text is bigger and clearer
    cropped_img = cv2.resize(cropped_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # im0 from YOLO comes in RGB, convert correctly to grayscale
    gray = cv2.cvtColor(cropped_img, cv2.COLOR_RGB2GRAY)

    # bilateral filter - smooths noise but keeps edges sharp
    blurred = cv2.bilateralFilter(gray, 7, 30, 30)

    # contrast enhancement using CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)

    # sharpening kernel
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    sharp = cv2.filter2D(enhanced, -1, kernel)

    cv2.imwrite("processed_plate.jpg", sharp)

    return sharp
