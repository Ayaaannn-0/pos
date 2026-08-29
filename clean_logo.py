import cv2
import numpy as np

def process():
    input_path = "static/logo.png"
    output_path_white = "static/logo_extracted_white.png"
    output_path_navy = "static/logo_extracted.png"
    
    img = cv2.imread(input_path)
    if img is None:
        print("Error loading image")
        return
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15
    )
    mask = cv2.bitwise_not(thresh)
    
    kernel = np.ones((3,3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.GaussianBlur(mask, (3,3), 0)
    mask[mask < 128] = 0
    
    # Find all contours
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    
    clean_mask = np.zeros_like(mask)
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        
        # The square border is very large. The text letters are small.
        # The top and bottom arcs are medium.
        # Let's filter out anything too large (the square)
        if w > 350 or h > 350:
            continue
            
        # Filter out the extra text on the right
        # The main text is roughly centered. 
        # The image width is 737. Center is ~368.
        # Extra text on right is probably > 480
        if x > 450:
            continue
            
        # Filter out anything too close to the edges which might be remnants of the square
        if x < 20 or y < 20 or x+w > 717 or y+h > 492:
            continue
            
        cv2.drawContours(clean_mask, [cnt], -1, 255, -1)
        
    # Crop tightly to the clean mask
    coords = cv2.findNonZero(clean_mask)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        pad = 10
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(img.shape[1] - x, w + 2*pad)
        h = min(img.shape[0] - y, h + 2*pad)
        
        # We will create two versions: white and navy
        
        # White version
        rgba_white = np.zeros((h, w, 4), dtype=np.uint8)
        rgba_white[:, :, 0] = 255
        rgba_white[:, :, 1] = 255
        rgba_white[:, :, 2] = 255
        rgba_white[:, :, 3] = clean_mask[y:y+h, x:x+w]
        cv2.imwrite(output_path_white, rgba_white)
        
        # Navy version
        rgba_navy = np.zeros((h, w, 4), dtype=np.uint8)
        rgba_navy[:, :, 0] = 65
        rgba_navy[:, :, 1] = 40
        rgba_navy[:, :, 2] = 20
        rgba_navy[:, :, 3] = clean_mask[y:y+h, x:x+w]
        cv2.imwrite(output_path_navy, rgba_navy)
        
        print("Successfully extracted clean logos without square and extra text.")
    else:
        print("Error: clean mask is empty.")

if __name__ == "__main__":
    process()
