# With database synchronization code borrowed from: 
# https://github.com/invoke-ai/InvokeAI/blob/231e5ec94afd91237fa57013e16f5cf0ce879f5d/invokeai/frontend/install/import_images.py

# TO DO  
# - Incremental updates are not detecting board assignment
 
import  InvokeDBAPI  as inv

import os
import os.path
import fnmatch
import re
import shutil
import json
import filecmp

import pandas as pd

import PIL
import PIL.ImageOps
import PIL.PngImagePlugin 

from tqdm import tqdm

from datetime import datetime, date 
import time
from time import sleep



def process_invokedb_backup():
    sync_boards = False
    catalog_images_data = []
    catalog_images_data_from_config = []

    try:
        with open("invokedb_manifest.json", 'r') as config_file:
            invokedb_list = json.load(config_file)

        for invokedb in invokedb_list["invokedb_list"]:
            TIMESTAMP_STRING = datetime.now().strftime("%Y%m%dT%H%M%SZ")
  
            print(f"Processing: {invokedb['name']}:")

            db_mapper = inv.DatabaseMapper(invokedb["db_file"], invokedb["backup_path"])
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
                catalog_images_data_from_config = get_images_catalog(db_mapper, invokedb["source_path"], invokedb_list["target_path"], invokedb_list["sessions_folder_name"], invokedb_list["boards_folder_name"])
                catalog_images_data.extend(catalog_images_data_from_config)
                print(">> BACKUP COMPLETE: ") 
            
            db_mapper.disconnect()

        return invokedb_list["target_path"], catalog_images_data

    except Exception as e:
        print(f">> Error in process_invokedb_backup: {e}")   
  

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
        WHERE ((im.created_at >= '{last_catalog_update_string}') or (im.updated_at >= '{last_catalog_update_string}')) and (im.is_intermediate=0)
        """)
    else:
        db_mapper.cursor.execute("""SELECT im.image_name, im.image_category, im.created_at, im.metadata, b.board_name   
        FROM images im
        LEFT OUTER JOIN board_images bi  
        ON bi.image_name = im.image_name  
        LEFT OUTER JOIN boards b  
        ON b.board_id  = bi.board_id
        WHERE (im.is_intermediate=0)
        """)
    
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
                img_info, png_width, png_height = inv.get_file_details(filepath)
                image_metadata, destination_needs_meta_update = inv.get_image_metadata(filepath)
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
                        inv.update_file_metadata_while_copying(
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
                img_info, png_width, png_height = inv.get_file_details(filepath)
                image_metadata, destination_needs_meta_update = inv.get_image_metadata(filepath)

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
                        inv.update_file_metadata_while_copying(
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


  
 
if __name__ == '__main__':
    # Backup images by date and boards (if any)
    # - Rename invokedb_manifest_sample.json file to invokedb_manifest.json
    # - Remove the dummy data and replace sample paths with your actual path

    # Save catalog to a JSON file  

    invokedb_archive_target_path, catalog_images_data = process_invokedb_backup()
    save_image_catalog(invokedb_archive_target_path, catalog_images_data)

    catalog_filename = os.path.join(invokedb_archive_target_path, "images_catalog.json")
    # catalog_filename = "E:\\Documents\\GenerativeAI\\_InvokeAI-Archive\\images_catalog.json"
    f_open = open(catalog_filename)
    json_response = json.load(f_open)
    catalog_df = pd.json_normalize(json_response["images"]) 
    # print(catalog_df.head(1).transpose())
    models_df = catalog_df["metadata.model.name"].value_counts()
    print("Top 10 models:")
    print(models_df.head(10)) 