# Stable Diffusion
Patches and customizations related to running Stable Diffusion locally.

For the moment, this repo only has some tweaks I created to improve InvokeAI:



### Session management

InvokeAI is great, but you end up quickly with a very large, single folder with ALL of your generated images.

I replaced the option to start the local website (option 2) with a call to my own .bat file.

That set_session.bat file will do a few things:

- Asks if you want to use an automatically generated daily session folder (and reuse it if you restart the website in the same day) or if you want to use a static session folder (_SANDBOX by default)
- If the _SANDBOX folder doesn't exist or has been renamed, a new folder will b created based on an empty session folder called '__NEW' (also in the repo for reference)
- You can change the name of the session files in the batch file



### Sortable models in drop down list

Editors like VS Studio code have extensions to sort yaml files by keys.

Once renamed and sorted, the drop down menu looks much easier to navigate without breaking anything with the models (the file name remains the same so it is possible to update the models without losing the new name).
