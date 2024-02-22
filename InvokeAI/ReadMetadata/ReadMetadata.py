import json
import pprint
from PIL import Image

# Local test file for Invoke 2.0+
# filename = 'G:\\Games-data\\CustomMods\\\_Github\\SkyrimLL\\StableDiffusion\\InvokeAI\\__NEW\\000001.bdebccbc.403813125.png'
# Local test file for Invoke 3.0+
# filename = 'E:\\Documents\\GenerativeAI\\InvokeAI-3.3.4\\images\\0c6e74a2-aa10-47cc-a1ef-6f9233b2ad43.png'

filename = 'E:\\Documents\\GenerativeAI\\InvokeAI-3.3.4\\images\\0c6e74a2-aa10-47cc-a1ef-6f9233b2ad43.png'
im = Image.open(filename)
im.load()

# pprint.pprint(im.info)

# InvokeAI Version 2.0
if "Dream" in im.info:
    image_metadata = json.loads(im.info["sd-metadata"])
else:
    image_metadata = json.loads(im.info["invokeai_metadata"]) 
 
print(f">> Decoding metadata for: {filename}")   

print(f">> Metadata: ")   
print(json.dumps(image_metadata, sort_keys=True, indent=4))

 