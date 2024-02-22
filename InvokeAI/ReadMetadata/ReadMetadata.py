import json
import pprint
from PIL import Image

filename = 'E:\\Documents\\GenerativeAI\\InvokeAI-3.3.4\\images\\0c6e74a2-aa10-47cc-a1ef-6f9233b2ad43.png'
im = Image.open(filename)
im.load()  # Needed only for .png EXIF data (see citation above)

image_metadata = json.loads(im.info["invokeai_metadata"])
 
print(f">> Decoding metadata for: {filename}")   
print(json.dumps(image_metadata, sort_keys=True, indent=4)) 
# pprint.pprint(im.info)
 