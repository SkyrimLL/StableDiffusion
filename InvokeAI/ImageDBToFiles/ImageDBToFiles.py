
import sqlite3
import os
import shutil
import json
import filecmp
from datetime import datetime
from datetime import date

catalog_images_data = []

def backup_images(db_file, source_path, target_path, sessions_folder, boards_folder):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("""SELECT im.image_name, im.image_category, im.created_at, im.metadata, b.board_name   
FROM images im
LEFT OUTER JOIN board_images bi  
ON bi.image_name = im.image_name  
LEFT OUTER JOIN boards b  
ON b.board_id  = bi.board_id""")
    
    # Fetch all rows from the result set
    images = cursor.fetchall()
    images_data = []

    # Create target folders if they don't exist
    for image in images:
        image_name, image_category, created_at, metadata, board_name = image

        # print(":: Get image fom DB")
        # print(image_name)
        # print(created_at)
        # print(board_name)
 
        date_format = '%Y-%m-%d %H:%M:%S.%f'
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

        try:
            if board_name:
                # Copy the image file to the category folder
                if copy_if_new(source_file_path, category_destination):
                    shutil.copy2(source_file_path, category_destination)
                    print(f"Image '{image_name}' copied successfully to '{category_destination}'")

            # Copy the image file to the date folder
            if copy_if_new(source_file_path, date_destination):
                shutil.copy2(source_file_path, date_destination)
                print(f"Image '{image_name}' copied successfully to '{date_destination}'")

        except FileNotFoundError:
            print(f"Error: File '{source_file_path}' not found.")
        except Exception as e:
            print(f"Error: {str(e)}")


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

    # Close the database connection
    conn.close()

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


def process_invokedb_backup():
    global catalog_images_data

    try:
        with open("invokedb_manifest.json", 'r') as f:
            invokedb_list = json.load(f)

        for invokedb in invokedb_list["invokedb_list"]:
            print(f"Processing: {invokedb['name']}:")
            catalog_images_data.append(backup_images(invokedb["db_file"], invokedb["source_path"], invokedb_list["target_path"], invokedb_list["sessions_folder_name"], invokedb_list["boards_folder_name"]))

        return invokedb_list["target_path"]

    except Exception as e:
        print(f">> Error opening config file: 'invokedb_manifest.json': {e}")   


if __name__ == '__main__':
    # Backup images by date and boards (if any)
    # - Rename invokedb_manifest_sample.json file to invokedb_manifest.json
    # - Remove the dummy data and replace sample paths with your actual path

    # Save catalog to a JSON file  

    invokedb_archive_target_path = process_invokedb_backup()

    save_image_catalog(invokedb_archive_target_path, catalog_images_data)
