import cv2
import numpy as np

def extract_logo_strict():
    input_path = "static/logo.png"
    output_path = "static/logo_extracted.png"
    
    img = cv2.imread(input_path)
    if img is None:
        print("Error loading image")
        return
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Use Adaptive Thresholding to defeat vignetting and uneven lighting
    # It calculates threshold for small regions, completely ignoring global lighting gradients.
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15
    )
    # thresh is 0 for text (dark), 255 for wall (light)
    
    # Invert so text is 255
    mask = cv2.bitwise_not(thresh)
    
    # Morphological opening to remove tiny noise specks from the wall
    kernel = np.ones((3,3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # Smooth the edges for anti-aliasing
    mask = cv2.GaussianBlur(mask, (3,3), 0)
    
    # HARD threshold the mask to absolutely ensure no faint background remains
    # Anything below 128 becomes 0, so NO faint vignette squares can exist
    mask[mask < 128] = 0
    
    rgba = np.zeros((img.shape[0], img.shape[1], 4), dtype=np.uint8)
    
    # Navy Blue #142841 -> B:65, G:40, R:20
    rgba[:, :, 0] = 65
    rgba[:, :, 1] = 40
    rgba[:, :, 2] = 20
    rgba[:, :, 3] = mask
    
    # Find bounding box
    coords = cv2.findNonZero(mask)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        pad = 20
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(rgba.shape[1] - x, w + 2*pad)
        h = min(rgba.shape[0] - y, h + 2*pad)
        rgba = rgba[y:y+h, x:x+w]
        
    cv2.imwrite(output_path, rgba)
    print("Strict logo extracted successfully")

if __name__ == "__main__":
    extract_logo_strict()
