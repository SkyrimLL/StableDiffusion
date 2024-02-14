

import sqlite3
import os
import shutil
from datetime import datetime
from datetime import date


def backup_images(db_file, source_path, target_path, sessions_folder, boards_folder):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("""SELECT im.image_name, im.created_at, b.board_name   
FROM images im
LEFT OUTER JOIN board_images bi  
ON bi.image_name = im.image_name  
LEFT OUTER JOIN boards b  
ON b.board_id  = bi.board_id""")
    
    # Fetch all rows from the result set
    images = cursor.fetchall()

    # Create target folders if they don't exist
    for image in images:
        image_name, created_at, board_name = image

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
        else:
            category_folder = target_path

        date_folder = os.path.join(target_path, sessions_folder)
        date_folder = os.path.join(date_folder, date_time_string)

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
                shutil.copy2(source_file_path, category_destination)
                print(f"Image '{image_name}' copied successfully to '{category_destination}'")

            # Copy the image file to the date folder
            shutil.copy2(source_file_path, date_destination)
            print(f"Image '{image_name}' copied successfully to '{date_destination}'")

        except FileNotFoundError:
            print(f"Error: File '{source_file_path}' not found.")
        except Exception as e:
            print(f"Error: {str(e)}")

    # Close the database connection
    conn.close()


# Backup images by date and boards (if any)
# Replace with your actual paths
db_file = "E:\\Tools\\InvokeAI\\databases\\invokeai.db"
source_path = "E:\\Documents\\GenerativeAI\\InvokeAI-3\\images\\"
target_path = "E:\\Documents\\GenerativeAI\\_InvokeAI-Archive\\" 

backup_images(db_file, source_path, target_path, "_SESSIONS", "_BOARDS")

db_file = "E:\\Tools\\InvokeAI-3.6.2\\databases\\invokeai.db"
source_path = "E:\\Tools\\InvokeAI-3.6.2\\outputs\\images\\"
target_path = "E:\\Documents\\GenerativeAI\\_InvokeAI-Archive\\" 

backup_images(db_file, source_path, target_path, "_SESSIONS", "_BOARDS")

