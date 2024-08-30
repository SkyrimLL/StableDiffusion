# With database synchronization code borrowed from: 
# https://github.com/invoke-ai/InvokeAI/blob/231e5ec94afd91237fa57013e16f5cf0ce879f5d/invokeai/frontend/install/import_images.py

# TO DO  

import sqlite3
import os
import os.path
import fnmatch
import re
import shutil
import json
import filecmp
import PIL
import PIL.ImageOps
import PIL.PngImagePlugin
from PIL import Image 
from datetime import datetime
from datetime import date
import uuid
from tqdm import tqdm
import time
from time import sleep

catalog_images_data = []

def backup_images(db_mapper, source_path, target_path, sessions_folder, boards_folder, full_update):
    print(":: Backing up new or updated images")

    catalog_filename = os.path.join(target_path, "images_catalog.json")

    try:
        last_catalog_update = time.strftime('%Y-%m-%d',  time.gmtime(os.path.getmtime(catalog_filename)) )
        last_catalog_update_string = last_catalog_update[:10] # .strftime("%Y-%m-%d")
        print(":: Checking for updates since: %s" % last_catalog_update_string)
    except:
        print(":: Last image catalog not found")
        full_update = True
    
    # print("created: %s" % time.ctime(os.path.getctime(catalog_filename)))
 
    if not full_update: 
        db_mapper.cursor.execute(f"""SELECT im.image_name, im.image_category, im.created_at, im.metadata, b.board_name   
        FROM images im
        LEFT OUTER JOIN board_images bi  
        ON bi.image_name = im.image_name  
        LEFT OUTER JOIN boards b  
        ON b.board_id  = bi.board_id
        WHERE (im.created_at >= '{last_catalog_update_string}') or (im.updated_at >= '{last_catalog_update_string}')
        """)
    else:
        db_mapper.cursor.execute("""SELECT im.image_name, im.image_category, im.created_at, im.metadata, b.board_name   
        FROM images im
        LEFT OUTER JOIN board_images bi  
        ON bi.image_name = im.image_name  
        LEFT OUTER JOIN boards b  
        ON b.board_id  = bi.board_id""")
    
    # Fetch all rows from the result set
    images = db_mapper.cursor.fetchall() 

    # Create target folders if they don't exist
    processed_files_count = 0
    pbar = tqdm(total=len(images)) 

    for image in images: 
        pbar.update(1)

        image_name, image_category, created_at, metadata, board_name = image

        # print(":: Get image fom DB")
        # print(image_name)
        # print(created_at)
        # print(board_name)
 
        created_at = created_at[:10] # Only keep the day no matter the time format
        date_format = '%Y-%m-%d'
        date_obj = datetime.strptime(created_at, date_format)
 
        date_time_string = date_obj.strftime("%Y-%m-%d")

        if board_name:
            category_folder = os.path.join(target_path, boards_folder)
            category_folder = os.path.join(category_folder, board_name)
            if image_category != "general":
                category_folder = os.path.join(category_folder, image_category)
        else:
            category_folder = target_path

        date_folder = os.path.join(target_path, sessions_folder)
        date_folder = os.path.join(date_folder, date_time_string)
        if image_category != "general":
            date_folder = os.path.join(date_folder, image_category)

        # Create folders if needed
        if board_name:
            os.makedirs(category_folder, exist_ok=True)

        os.makedirs(date_folder, exist_ok=True)

        # Construct the source path
        source_file_path = os.path.join(source_path, image_name)

        # Construct the destination paths for copying
        category_destination = os.path.join(category_folder, image_name)
        date_destination = os.path.join(date_folder, image_name)

        is_file_processed = False 

        try:
            if board_name:
                # Copy the image file to the category folder
                if copy_if_new(source_file_path, category_destination):
                    shutil.copy2(source_file_path, category_destination)
                    is_file_processed = True
                    # print(f"Image '{image_name}' copied successfully to '{category_destination}'")

            # Copy the image file to the date folder
            if copy_if_new(source_file_path, date_destination):
                shutil.copy2(source_file_path, date_destination)
                is_file_processed = True
                # print(f"Image '{image_name}' copied successfully to '{date_destination}'")

            if is_file_processed:
                processed_files_count += 1

        except FileNotFoundError:
            print(f"Error: File '{source_file_path}' not found.")
        except Exception as e:
            print(f"Error: {str(e)}")

    pbar.close()

    print(f":: Number of files backed up: {processed_files_count}") 


def get_images_catalog(db_mapper, source_path, target_path, sessions_folder, boards_folder):
    print(":: Generating full image catalog")
 
    db_mapper.cursor.execute("""SELECT im.image_name, im.image_category, im.created_at, im.metadata, b.board_name   
FROM images im
LEFT OUTER JOIN board_images bi  
ON bi.image_name = im.image_name  
LEFT OUTER JOIN boards b  
ON b.board_id  = bi.board_id""")
    
    # Fetch all rows from the result set
    images = db_mapper.cursor.fetchall()
    images_data = []

    # Create target folders if they don't exist
    processed_files_count = 0
    pbar = tqdm(total=len(images)) 

    for image in images: 
        pbar.update(1)

        image_name, image_category, created_at, metadata, board_name = image

        # print(":: Get image fom DB")
        # print(image_name)
        # print(created_at)
        # print(board_name)
 
        created_at = created_at[:10] # Only keep the day no matter the time format
        date_format = '%Y-%m-%d'
        date_obj = datetime.strptime(created_at, date_format)
 
        date_time_string = date_obj.strftime("%Y-%m-%d")

        if board_name:
            category_folder = os.path.join(target_path, boards_folder)
            category_folder = os.path.join(category_folder, board_name)
            if image_category != "general":
                category_folder = os.path.join(category_folder, image_category)
        else:
            category_folder = target_path

        date_folder = os.path.join(target_path, sessions_folder)
        date_folder = os.path.join(date_folder, date_time_string)
        if image_category != "general":
            date_folder = os.path.join(date_folder, image_category)

        # Construct the source path
        source_file_path = os.path.join(source_path, image_name)

        # Construct the destination paths for copying
        category_destination = os.path.join(category_folder, image_name)
        date_destination = os.path.join(date_folder, image_name)

        # Prepare image catalog item
        if not metadata:
            metadata = "{}"
        
        this_image_data = {
            "name": image_name,
            "board": board_name,
            "session_file_path": date_destination,
            "board_file_path": category_destination,
            "type": image_category,
            "metadata": json.loads(metadata)
        }
        images_data.append(this_image_data)

    pbar.close()
  
    return images_data


def copy_if_new(source_file, target_file):
    copyfileflag = False
    # print("Looking for: "+ join(root, fn))
    # print(":: into    : "+ target_file)

    if (not os.path.exists(target_file)):
        # foundfiles = foundfiles + "\n" + "      Found new file: " + target_file   
        copyfileflag = True
    elif (os.path.exists(source_file) and os.path.exists(target_file)):
        if (os.path.getmtime(source_file) > os.path.getmtime(target_file)):
            # Copy newer files - updated recently
            # foundfiles = foundfiles + "\n" + "      Updating newer file: " + target_file   
            copyfileflag = True
        elif (not filecmp.cmp(source_file, target_file)):
            # Copy new or missing files
            # foundfiles = foundfiles + "\n" + "      Updating different file: " + target_file   
            copyfileflag = True 

    return copyfileflag 


def save_image_catalog(target_path, catalog_images_data):
    catalog_data = {"last_updated": datetime.today().strftime('%Y-%m-%d'), "images": catalog_images_data} 
    catalog_filename = os.path.join(target_path, "images_catalog.json")

    print(f">> Updating images catalog: {catalog_filename}")

    try:
        # Write the updated data to the file
        with open(catalog_filename, 'w') as file:
            json.dump(catalog_data, file, indent=2)
 
    except Exception as e:
        print(f">> Error updating catalog: {catalog_filename}: {e}")


def get_image_metadata(filename):
    destination_needs_meta_update = False
    parser = InvokeAIMetadataParser()

    # pprint.pprint(im.info)
    img_info, png_width, png_height = get_file_details(filename)

    # parse metadata
    destination_needs_meta_update = True
    log_version_note = "(Unknown)"
    if "invokeai_metadata" in img_info:
        # for the latest, we will just re-emit the same json, no need to parse/modify
        converted_field = None
        latest_json_string = img_info.get("invokeai_metadata")
        latest_json_string = latest_json_string.replace("'", "") # need to remove single quote to avoid error on json conversion

        log_version_note = "3.0.0+"
        destination_needs_meta_update = False
    else:
        if "sd-metadata" in img_info:
            converted_field = parser.parse_meta_tag_sd_metadata(json.loads(img_info.get("sd-metadata")))
        elif "invokeai" in img_info:
            converted_field = parser.parse_meta_tag_invokeai(json.loads(img_info.get("invokeai")))
        elif "dream" in img_info:
            converted_field = parser.parse_meta_tag_dream(img_info.get("dream"))
        elif "Dream" in img_info:
            converted_field = parser.parse_meta_tag_dream(img_info.get("Dream"))
        else:
            converted_field = InvokeAIMetadata()
            destination_needs_meta_update = False
            # print("File does not have metadata from known Invoke AI versions, add only, no update!")

        # use the loaded img dimensions if the metadata didnt have them
        if converted_field.width is None:
            converted_field.width = png_width
        if converted_field.height is None:
            converted_field.height = png_height

        log_version_note = converted_field.imported_app_version if converted_field else "NoVersion"
        log_version_note = log_version_note or "NoVersion"

        latest_json_string = converted_field.to_json()
    
    # print(f">> Decoding metadata for: {filename}")   
    # print(f">> Metadata: ")   
    # print(json.dumps(latest_json_string, sort_keys=True, indent=4))

    return(latest_json_string, destination_needs_meta_update)


def sync_boards_archive_to_db(db_mapper, input_dir, boards_folder_name, _invokedb):
    print(f">> Synchronizing BOARDS archive to current database") 
    db_file = _invokedb["db_file"]
    img_dir = _invokedb["source_path"] 
    thumbnail_dir = _invokedb["thumbnail_path"] 

    # For each image in Recursively scanned BOARDS target path
    totalfilecount = 0
    skipped_images_count = 0
    pattern = "*.png"
    regexpattern = fnmatch.translate(pattern)
    prog = re.compile(regexpattern) 

    for (root, dirs, files) in os.walk(os.path.join(input_dir,boards_folder_name)):

        filecount = 0 
        pbar = tqdm(total=len(files)) 
        path, folder_name = os.path.split(root)
        pbar.set_description("Processing %s" % folder_name)

        for image_name in files:
            m = prog.match(image_name)
            if m:
                sleep(0.1)
                pbar.update(1)
                # Exclude some files
                # print(f"{root} / {fn}")
                filecount += 1
                totalfilecount += 1

                filepath = os.path.join(root, image_name)
                img_info, png_width, png_height = get_file_details(filepath)
                image_metadata, destination_needs_meta_update = get_image_metadata(filepath)
                #   Get board name - If board doesn't exist in DB, create it
                path, board_name = os.path.split(root)
                # print(f"{board_name} / {image_name}")
                board_id = db_mapper.get_board_id_with_create(board_name)
                #   If image doesn't exist in DB

                if db_mapper.does_image_exist(image_name):
                    # print(">>>> IMAGE EXISTS - Skipping")
                    skipped_images_count += 1
                else: 
                    # print(f">>>> NEW IMAGE: {board_name} / {image_name}")
                    #   add it to DB and copy to invoke folder 
                    # copy image to invoke folder
                    if destination_needs_meta_update:
                        # print("Updating metadata while copying...")
                        update_file_metadata_while_copying(
                            filepath, os.path.join(img_dir, image_name), "invokeai_metadata", image_metadata 
                        )
                    else:
                        # print("No metadata update necessary, copying only...")
                        shutil.copy2(filepath, os.path.join(img_dir, image_name))
                    
                    # create thumbnail
                    # print("Creating thumbnail...")
                    thumbnail_path = os.path.join(thumbnail_dir, os.path.splitext(image_name)[0]) + ".webp"
                    thumbnail_size = 256, 256
                    with PIL.Image.open(filepath) as source_image:
                        source_image.thumbnail(thumbnail_size)
                        source_image.save(thumbnail_path, "webp")

                    modified_time = datetime.fromtimestamp(os.path.getmtime(filepath))  
                    # print("add_new_image_to_database")
                    db_mapper.add_new_image_to_database(image_name, png_width, png_height, image_metadata , modified_time)
                    # print("add_image_to_board")
                    db_mapper.add_image_to_board(image_name, board_id)

        pbar.close()
    
    print(f">>>> Skipped {skipped_images_count} images")


def sync_sessions_archive_to_db(db_mapper, input_dir, sessions_folder_name, _invokedb):
    print(f">> Synchronizing SESSIONS archive to current database") 
    db_file = _invokedb["db_file"]
    img_dir = _invokedb["source_path"] 
    thumbnail_dir = _invokedb["thumbnail_path"] 

    # For each image in Recursively scanned BOARDS target path
    totalfilecount = 0
    skipped_images_count = 0
    pattern = "*.png"
    regexpattern = fnmatch.translate(pattern)
    prog = re.compile(regexpattern) 

    for (root, dirs, files) in os.walk(os.path.join(input_dir,sessions_folder_name)):

        filecount = 0 
        pbar = tqdm(total=len(files)) 
        path, folder_name = os.path.split(root)
        pbar.set_description("Processing %s" % folder_name)

        date_str = folder_name
        date_format = '%Y-%m-%d'

        date_obj = datetime.strptime(date_str, date_format)
        modified_time = date_obj.strftime('%Y-%m-%d') 
        
        for image_name in files:
            m = prog.match(image_name)
            if m:
                sleep(0.1)
                pbar.update(1)

                # Exclude some files
                # print(f"{root} / {fn}")
                filecount += 1
                totalfilecount += 1

                filepath = os.path.join(root, image_name)
                img_info, png_width, png_height = get_file_details(filepath)
                image_metadata, destination_needs_meta_update = get_image_metadata(filepath)

                if db_mapper.does_image_exist(image_name):
                    # print(">>>> IMAGE EXISTS - Skipping")
                    # Update image with session folder name as modified time instead
                    db_mapper.update_image_timestamp(image_name, modified_time)
                    skipped_images_count += 1
                else: 
                    # print(f">>>> NEW IMAGE:  {image_name}")
                    #   add it to DB and copy to invoke folder 
                    # copy image to invoke folder
                    if destination_needs_meta_update:
                        # print("Updating metadata while copying...")
                        update_file_metadata_while_copying(
                            filepath, os.path.join(img_dir, image_name), "invokeai_metadata", image_metadata 
                        )
                    else:
                        # print("No metadata update necessary, copying only...")
                        shutil.copy2(filepath, os.path.join(img_dir, image_name))
                    
                    # create thumbnail
                    # print("Creating thumbnail...")
                    thumbnail_path = os.path.join(thumbnail_dir, os.path.splitext(image_name)[0]) + ".webp"
                    thumbnail_size = 256, 256
                    with PIL.Image.open(filepath) as source_image:
                        source_image.thumbnail(thumbnail_size)
                        source_image.save(thumbnail_path, "webp")

                    # modified_time = datetime.fromtimestamp(os.path.getmtime(filepath)) 
                    # Use session folder name as modified time instead  
                    # print("add_new_image_to_database")
                    db_mapper.add_new_image_to_database(image_name, png_width, png_height, image_metadata , modified_time)

        pbar.close()

    print(f">>>> Skipped {skipped_images_count} images")


def repair_image_dates_db(db_mapper):
    print(f">> Synchronizing SESSIONS archive to current database") 
    input_path = "E:\\Documents\\GenerativeAI\\_old\\_InvokeAI-Archive\\_SESSIONS" 

    # For each image in Recursively scanned BOARDS target path
    totalfilecount = 0
    processed_images_count = 0
    pattern = "*.png"
    regexpattern = fnmatch.translate(pattern)
    prog = re.compile(regexpattern) 

    for (root, dirs, files) in os.walk(input_path):

        filecount = 0 
        pbar = tqdm(total=len(files)) 
        path, folder_name = os.path.split(root)
        pbar.set_description("Processing %s" % folder_name)

        if (folder_name != "user") and (folder_name != "control") and (folder_name != "mask"):
            for image_name in files:
                m = prog.match(image_name)
                if m:
                    sleep(0.1)
                    pbar.update(1)

                    # Exclude some files
                    # print(f"{root} / {fn}")
                    filecount += 1
                    totalfilecount += 1

                    filepath = os.path.join(root, image_name) 

                    if db_mapper.does_image_exist(image_name):
                        # print(">>>> IMAGE EXISTS - Skipping")
                        processed_images_count += 1
                        
                        date_str = folder_name
                        date_format = '%Y-%m-%d'

                        date_obj = datetime.strptime(date_str, date_format)
                        modified_time = date_obj.strftime('%Y-%m-%d') 
                        # print(f" UPATE images SET updated_at='{modified_time}' WHERE image_name='{image_name}'")
                        db_mapper.update_image_timestamp(image_name, modified_time)

        pbar.close()

    print(f">>>> Processed {processed_images_count} images")


def process_invokedb_backup():
    sync_boards = False
    try:
        with open("invokedb_manifest.json", 'r') as config_file:
            invokedb_list = json.load(config_file)

        for invokedb in invokedb_list["invokedb_list"]:
            TIMESTAMP_STRING = datetime.now().strftime("%Y%m%dT%H%M%SZ")
  
            print(f"Processing: {invokedb['name']}:")

            db_mapper = DatabaseMapper(invokedb["db_file"], invokedb["backup_path"])
            db_mapper.connect()
            db_mapper.backup(TIMESTAMP_STRING)

            if "sync_boards" in invokedb:
                if invokedb["sync_boards"]:
                    sync_boards = True
                    
            if sync_boards:   
                print(">> SYNC STARTED: ")   
                sync_boards_archive_to_db(db_mapper, invokedb_list["target_path"],invokedb_list["boards_folder_name"], invokedb)
                sync_sessions_archive_to_db(db_mapper, invokedb_list["target_path"],invokedb_list["sessions_folder_name"], invokedb)
                print(">> SYNC COMPLETE: Backup and empty your Archive folder to avoid duplicates. Run script again with sync_boards set to False in manifest.")
            else:
                print(">> BACKUP STARTED: ") 
                # repair_image_dates_db(db_mapper)
                backup_images(db_mapper, invokedb["source_path"], invokedb_list["target_path"], invokedb_list["sessions_folder_name"], invokedb_list["boards_folder_name"], invokedb["full_update"])
                catalog_images_data.append(get_images_catalog(db_mapper, invokedb["source_path"], invokedb_list["target_path"], invokedb_list["sessions_folder_name"], invokedb_list["boards_folder_name"]))
                print(">> BACKUP COMPLETE: ") 
            
            db_mapper.disconnect()

        return invokedb_list["target_path"], catalog_images_data

    except Exception as e:
        print(f">> Error in process_invokedb_backup: {e}")   


def uuid_string() -> str:
    res = uuid.uuid4()
    return str(res)


def get_file_details(filepath):
    """Retrieve the embedded metedata fields and dimensions from an image file."""
    with PIL.Image.open(filepath) as img:
        img.load()
        png_width, png_height = img.size
        img_info = img.info
    return img_info, png_width, png_height

def update_file_metadata_while_copying(filepath, file_destination_path, tag_name, tag_value):
    """Perform a metadata update with save to a new destination which accomplishes a copy while updating metadata."""
    with PIL.Image.open(filepath) as target_image:
        existing_img_info = target_image.info
        metadata = PIL.PngImagePlugin.PngInfo()
        # re-add any existing invoke ai tags unless they are the one we are trying to add
        for key in existing_img_info:
            if key != tag_name and key in ("dream", "Dream", "sd-metadata", "invokeai", "invokeai_metadata"):
                metadata.add_text(key, existing_img_info[key])
        metadata.add_text(tag_name, tag_value)
        target_image.save(file_destination_path, pnginfo=metadata)
    
class DatabaseMapper:
    """Class to abstract database functionality."""

    def __init__(self, database_path, database_backup_dir):
        self.database_path = database_path
        self.database_backup_dir = database_backup_dir
        self.connection = None
        self.cursor = None

    def connect(self):
        """Open connection to the database."""
        self.connection = sqlite3.connect(self.database_path)
        self.cursor = self.connection.cursor()

    def get_board_names(self):
        """Get a list of the current board names from the database."""
        sql_get_board_name = "SELECT board_name FROM boards"
        self.cursor.execute(sql_get_board_name)
        rows = self.cursor.fetchall()
        return [row[0] for row in rows]

    def does_image_exist(self, image_name):
        """Check database if a image name already exists and return a boolean."""
        sql_get_image_by_name = f"SELECT image_name FROM images WHERE image_name='{image_name}'"
        self.cursor.execute(sql_get_image_by_name)
        rows = self.cursor.fetchall()
        return True if len(rows) > 0 else False

    def add_new_image_to_database(self, filename, width, height, metadata, modified_date_string):
        """Add an image to the database."""
        sql_add_image = f"""INSERT INTO images (image_name, image_origin, image_category, width, height, session_id, node_id, metadata, is_intermediate, created_at, updated_at)
VALUES ('{filename}', 'internal', 'general', {width}, {height}, null, null, '{metadata}', 0, '{modified_date_string}', '{modified_date_string}')"""
        self.cursor.execute(sql_add_image)
        self.connection.commit()
 
    def update_image_timestamp(self, filename, modified_date_string):
        """Update image timestamp."""
        sql_update_image = f"UPDATE images SET created_at='{modified_date_string}' WHERE image_name='{filename}'"
        self.cursor.execute(sql_update_image)
        self.connection.commit()

    def get_board_id_with_create(self, board_name):
        """Get the board id for supplied name, and create the board if one does not exist."""
        sql_find_board = f"SELECT board_id FROM boards WHERE board_name='{board_name}' COLLATE NOCASE"
        self.cursor.execute(sql_find_board)
        rows = self.cursor.fetchall()
        if len(rows) > 0:
            return rows[0][0]
        else:
            board_date_string = datetime.now().date().isoformat()
            new_board_id = uuid_string()
            sql_insert_board = f"INSERT INTO boards (board_id, board_name, created_at, updated_at) VALUES ('{new_board_id}', '{board_name}', '{board_date_string}', '{board_date_string}')"
            self.cursor.execute(sql_insert_board)
            self.connection.commit()
            return new_board_id

    def add_image_to_board(self, filename, board_id):
        """Add an image mapping to a board."""
        add_datetime_str = datetime.now().isoformat()
        sql_add_image_to_board = f"""INSERT INTO board_images (board_id, image_name, created_at, updated_at)
            VALUES ('{board_id}', '{filename}', '{add_datetime_str}', '{add_datetime_str}')"""
        self.cursor.execute(sql_add_image_to_board)
        self.connection.commit()

    def disconnect(self):
        """Disconnect from the db, cleaning up connections and cursors."""
        if self.cursor is not None:
            self.cursor.close()
        if self.connection is not None:
            self.connection.close()

    def backup(self, timestamp_string):
        """Take a backup of the database."""
        if not os.path.exists(self.database_backup_dir):
            print(f"Database backup directory {self.database_backup_dir} does not exist -> creating...", end="")
            os.makedirs(self.database_backup_dir)
            print("Done!")
        database_backup_path = os.path.join(self.database_backup_dir, f"backup-{timestamp_string}-invokeai.db")
        print(f"Making DB Backup at {database_backup_path}...", end="")
        shutil.copy2(self.database_path, database_backup_path)
        print("Done!")



class InvokeAIMetadata:
    """DTO for core Invoke AI generation properties parsed from metadata."""

    def __init__(self):
        pass

    def __str__(self):
        formatted_str = f"{self.generation_mode}~{self.steps}~{self.cfg_scale}~{self.model_name}~{self.scheduler}~{self.seed}~{self.width}~{self.height}~{self.rand_device}~{self.strength}~{self.init_image}"
        formatted_str += f"\r\npositive_prompt: {self.positive_prompt}"
        formatted_str += f"\r\nnegative_prompt: {self.negative_prompt}"
        return formatted_str

    generation_mode = None
    steps = None
    cfg_scale = None
    model_name = None
    scheduler = None
    seed = None
    width = None
    height = None
    rand_device = None
    strength = None
    init_image = None
    positive_prompt = None
    negative_prompt = None
    imported_app_version = None

    def to_json(self):
        """Convert the active instance to json format."""
        prop_dict = {}
        prop_dict["generation_mode"] = self.generation_mode
        # dont render prompt nodes if neither are set to avoid the ui thinking it can set them
        # if at least one exists, render them both, but use empty string instead of None if one of them is empty
        # this allows the field that is empty to actually be cleared byt he UI instead of leaving the previous value
        if self.positive_prompt or self.negative_prompt:
            prop_dict["positive_prompt"] = "" if self.positive_prompt is None else self.positive_prompt.replace("'", "")
            prop_dict["negative_prompt"] = "" if self.negative_prompt is None else self.negative_prompt.replace("'", "")

        prop_dict["width"] = self.width
        prop_dict["height"] = self.height
        # only render seed if it has a value to avoid ui thinking it can set this and then error
        if self.seed:
            prop_dict["seed"] = self.seed
        prop_dict["rand_device"] = self.rand_device
        prop_dict["cfg_scale"] = self.cfg_scale
        prop_dict["steps"] = self.steps
        prop_dict["scheduler"] = self.scheduler
        prop_dict["clip_skip"] = 0
        prop_dict["model"] = {}
        prop_dict["model"]["model_name"] = self.model_name
        prop_dict["model"]["base_model"] = None
        prop_dict["controlnets"] = []
        prop_dict["loras"] = []
        prop_dict["vae"] = None
        prop_dict["strength"] = self.strength
        prop_dict["init_image"] = self.init_image
        prop_dict["positive_style_prompt"] = None
        prop_dict["negative_style_prompt"] = None
        prop_dict["refiner_model"] = None
        prop_dict["refiner_cfg_scale"] = None
        prop_dict["refiner_steps"] = None
        prop_dict["refiner_scheduler"] = None
        prop_dict["refiner_aesthetic_store"] = None
        prop_dict["refiner_start"] = None
        prop_dict["imported_app_version"] = self.imported_app_version

        return json.dumps(prop_dict)


class InvokeAIMetadataParser:
    """Parses strings with json data  to find Invoke AI core metadata properties."""

    def __init__(self):
        pass

    def parse_meta_tag_dream(self, dream_string):
        """Take as input an png metadata json node for the 'dream' field variant from prior to 1.15"""
        props = InvokeAIMetadata()

        props.imported_app_version = "pre1.15"
        seed_match = re.search("-S\\s*(\\d+)", dream_string)
        if seed_match is not None:
            try:
                props.seed = int(seed_match[1])
            except ValueError:
                props.seed = None
            raw_prompt = re.sub("(-S\\s*\\d+)", "", dream_string)
        else:
            raw_prompt = dream_string

        pos_prompt, neg_prompt = self.split_prompt(raw_prompt)

        props.positive_prompt = pos_prompt
        props.negative_prompt = neg_prompt

        return props

    def parse_meta_tag_sd_metadata(self, tag_value):
        """Take as input an png metadata json node for the 'sd-metadata' field variant from 1.15 through 2.3.5 post 2"""
        props = InvokeAIMetadata()

        props.imported_app_version = tag_value.get("app_version")
        props.model_name = tag_value.get("model_weights")
        img_node = tag_value.get("image")
        if img_node is not None:
            props.generation_mode = img_node.get("type")
            props.width = img_node.get("width")
            props.height = img_node.get("height")
            props.seed = img_node.get("seed")
            props.rand_device = "cuda"  # hardcoded since all generations pre 3.0 used cuda random noise instead of cpu
            props.cfg_scale = img_node.get("cfg_scale")
            props.steps = img_node.get("steps")
            props.scheduler = self.map_scheduler(img_node.get("sampler"))
            props.strength = img_node.get("strength")
            if props.strength is None:
                props.strength = img_node.get("strength_steps")  # try second name for this property
            props.init_image = img_node.get("init_image_path")
            if props.init_image is None:  # try second name for this property
                props.init_image = img_node.get("init_img")
            # remove the path info from init_image so if we move the init image, it will be correctly relative in the new location
            if props.init_image is not None:
                props.init_image = os.path.basename(props.init_image)
            raw_prompt = img_node.get("prompt")
            if isinstance(raw_prompt, list):
                raw_prompt = raw_prompt[0].get("prompt")

            props.positive_prompt, props.negative_prompt = self.split_prompt(raw_prompt)

        return props

    def parse_meta_tag_invokeai(self, tag_value):
        """Take as input an png metadata json node for the 'invokeai' field variant from 3.0.0 beta 1 through 5"""
        props = InvokeAIMetadata()

        props.imported_app_version = "3.0.0 or later"
        props.generation_mode = tag_value.get("type")
        if props.generation_mode is not None:
            props.generation_mode = props.generation_mode.replace("t2l", "txt2img").replace("l2l", "img2img")

        props.width = tag_value.get("width")
        props.height = tag_value.get("height")
        props.seed = tag_value.get("seed")
        props.cfg_scale = tag_value.get("cfg_scale")
        props.steps = tag_value.get("steps")
        props.scheduler = tag_value.get("scheduler")
        props.strength = tag_value.get("strength")
        props.positive_prompt = tag_value.get("positive_conditioning")
        props.negative_prompt = tag_value.get("negative_conditioning")

        return props

    def map_scheduler(self, old_scheduler):
        """Convert the legacy sampler names to matching 3.0 schedulers"""

        # this was more elegant as a case statement, but that's not available in python 3.9
        if old_scheduler is None:
            return None
        scheduler_map = {
            "ddim": "ddim",
            "plms": "pnmd",
            "k_lms": "lms",
            "k_dpm_2": "kdpm_2",
            "k_dpm_2_a": "kdpm_2_a",
            "dpmpp_2": "dpmpp_2s",
            "k_dpmpp_2": "dpmpp_2m",
            "k_dpmpp_2_a": None,  # invalid, in 2.3.x, selecting this sample would just fallback to last run or plms if new session
            "k_euler": "euler",
            "k_euler_a": "euler_a",
            "k_heun": "heun",
        }
        return scheduler_map.get(old_scheduler)

    def split_prompt(self, raw_prompt: str):
        """Split the unified prompt strings by extracting all negative prompt blocks out into the negative prompt."""
        if raw_prompt is None:
            return "", ""
        raw_prompt_search = raw_prompt.replace("\r", "").replace("\n", "")
        matches = re.findall(r"\[(.+?)\]", raw_prompt_search)
        if len(matches) > 0:
            negative_prompt = ""
            if len(matches) == 1:
                negative_prompt = matches[0].strip().strip(",")
            else:
                for match in matches:
                    negative_prompt += f"({match.strip().strip(',')})"
            positive_prompt = re.sub(r"(\[.+?\])", "", raw_prompt_search).strip()
        else:
            positive_prompt = raw_prompt_search.strip()
            negative_prompt = ""

        return positive_prompt, negative_prompt


if __name__ == '__main__':
    # Backup images by date and boards (if any)
    # - Rename invokedb_manifest_sample.json file to invokedb_manifest.json
    # - Remove the dummy data and replace sample paths with your actual path

    # Save catalog to a JSON file  

    invokedb_archive_target_path, catalog_images_data = process_invokedb_backup()

    save_image_catalog(invokedb_archive_target_path, catalog_images_data)
