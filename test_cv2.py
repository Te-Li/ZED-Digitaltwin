import cv2
d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
print("DICT_5X5_100 marker count:", d.bytesList.shape[0])