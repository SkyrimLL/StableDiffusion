import json
import pprint
from PIL import Image

filename = 'E:\\Documents\\GenerativeAI\\InvokeAI-2\\_SANDBOX_20230823\\000137.9213cf41.3936649406.png'
im = Image.open(filename)
im.load()  # Needed only for .png EXIF data (see citation above)
 
print(json.dumps(im.info, sort_keys=True, indent=4)) 
# pprint.pprint(im.info)
 