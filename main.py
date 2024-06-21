
import io, os, json
from pathlib import Path, PurePath
from shutil import rmtree

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

#lists all items in specified folder
def list_folder(folder_id : str) -> dict:
    items = {}
    page_token = None
    while True:
        response = (
            service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="files(id, name)",
                    includeItemsFromAllDrives="true",
                    supportsAllDrives="true"
          )
          .execute()
        )
        if len(response) == 0:
            raise PermissionError("Could not access the drive under which folder exists. Please add the service account as a member to it.") 

        for file in response.get("files", []):
            #show added files
            if verbose: print(f'Found file: {file.get("name")}, {file.get("id")}')
            items[str.lower(file.get("name"))] = file.get("id")
        page_token = response.get("nextPageToken", None)
        if page_token is None:
            break

    return items

#finds the item in the folder, returns id of item
def find_in_gdrive_folder(folder_id : str, item_name : str) -> str:
    folder_items = list_folder(folder_id)
    if item_name in folder_items:
        return folder_items[item_name]
    raise ValueError(f"Could not find '{item_name}' in inputted folder.")

#checks if matching item exists in downloads folder for inputted platform
def find_in_local_folder(platform : str, item_name :str) -> bool:
    file_name, file_type = os.path.splitext(item_name)
    if file_type in ['.zip','.tar','.gz']:
        downloaded_path = downloads_path / platform / file_name #it's a directory that will have been unzipped; check for the directory
    else: 
        downloaded_path = downloads_path / platform / item_name #check for the file itself

    file_exists = Path.exists(downloaded_path)  
    if verbose:
        if file_exists: print(f'Downloaded copy of {item_name} exists already at {downloaded_path}.')
        else: print(f'Downloaded copy of {item_name} was not found in {downloads_path / platform}')

    return file_exists


#downloads specified file id and saves it to "<file_name>" under downloads_path
def download_file(file_name : str, file_id : str, dl_dir : Path):
    if verbose: print(f'Downloading file: {file_name}')
    request = service.files().get_media(fileId=file_id)
    file = io.BytesIO()
    downloader = MediaIoBaseDownload(file, request)
    done = False

    while done is False:
        status, done = downloader.next_chunk()
        if verbose: print(f"Download progress: {status.resumable_progress} / {status.total_size} ({(status.resumable_progress / status.total_size*100):.2f}%)")

    #write to download directory
    with open(dl_dir / f'{file_name}', 'wb') as f:
        f.write(file.getbuffer())

#wrapper for getting input variables
def get_input_variable(name : str, required=False, default=None, expected_type=str) -> str:
    try:
        input_variable=os.environ[name]
        if len(input_variable) == 0:
            return None #prefer None over empty strings

        if type(input_variable) != expected_type:
            input_variable = expected_type(input_variable)
        return input_variable
    except KeyError:
        if required: raise KeyError(f'Required input is missing: {name}!')
        return default 

def write_to_output(output_name, output_value):
    if verbose: print(f'{output_name}: {output_value}')
    if gha_output:
        with open(output_file, "a") as f:
            f.write(f'{output_name}={output_value}\n')
    else:
        print(f'::set-output name={output_name}::{output_value}')

if __name__ == '__main__':
    env_folder_id = get_input_variable('INPUT_ENVFOLDERID', required=True)          #folder id for environment folder in project gdrive
    credentials = get_input_variable('INPUT_CREDENTIALS', required=True)            #google drive api credentials
    platform_names = get_input_variable('INPUT_PLATFORMNAMES', required=True)       #platforms to build for
    unity_version = get_input_variable("INPUT_UNITYVERSION")
    reuse_downloads = get_input_variable("INPUT_REUSEDOWNLOADS", required=True, expected_type=bool)
    verbose = get_input_variable("INPUT_VERBOSE", required=False, default=True, expected_type=bool)

    #parse platform list
    platform_names=platform_names.replace('\'', '')
    platform_names=platform_names.replace('\"', '')
    platform_names=platform_names.replace('[','')
    platform_names=platform_names.replace(']','')
    platform_names=platform_names.replace(' ', '')
    platform_names=[ str.lower(platform) for platform in platform_names.split(',') ]
    if verbose: print(f'Inputted list of platforms parsed as: {platform_names}')
    if platform_names == ['']:
        print('Empty string was passed in for platform_names. Exiting early.')
        quit(1)


    #get output file for actions
    output_file = os.getenv('GITHUB_OUTPUT')
    if output_file is None:
        if verbose: print('GITHUB_OUTPUT could not be found. Assuming that this is not being run on a GHA runner.')
    else: 
        if verbose: print('GITHUB_OUTPUT was found.')
    gha_output = output_file is not None  #...for some reason

    #authenticate and create api client
    if verbose: print('Connecting to Google API.')
    SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
    credentials = json.loads(credentials)
    creds, _ = google.auth.load_credentials_from_dict(credentials)
    service = build("drive", "v3", credentials=creds)

    #since this on a docker container, there will only be one drive (C:)
    downloads_path = Path('C:/installers')

    #write downloads path to output
    write_to_output('downloads-path', downloads_path)
    
    print(f'Downloads path is {downloads_path}')
    if not reuse_downloads:
        if Path.exists(downloads_path):
            rmtree(downloads_path) 
    if not Path.exists(downloads_path):
        Path.mkdir(downloads_path)

    if verbose: print('Downloading files from Google drive.')
    try:
        for platform in platform_names:
            #make directory for platform
            curr_platform_env_path = downloads_path / platform
            if not reuse_downloads or not Path.exists(curr_platform_env_path):
                Path.mkdir(curr_platform_env_path)

            #skip platforms that don't need any downloads
            if platform == 'wingdk' or platform == 'standalonewindows64':
                continue

            #get the folder for the requested platform
            plat_folder_id = find_in_gdrive_folder(env_folder_id, platform)

            #download its contents
            if verbose: print(f'Found platform environment folder.')
            for item_name, item_id in list_folder(plat_folder_id).items():
                item_name=str.lower(item_name) #standardize names
                file_extension = os.path.splitext(item_name)[1]
                if os.path.splitext(item_name)[1] != '.exe' or 'unitysetup' not in str.lower(item_name):
                    continue

                if not reuse_downloads or not find_in_local_folder(platform=platform, item_name=item_name):
                    download_file(item_name, item_id, curr_platform_env_path)

            print(f'Completed download for {platform}')

    except HttpError as error:
        print(f'An error has occurred: {error}')
        quit()

    #get all the RELATIVE paths for all add-on installers, relative to downloads_path
    installer_paths = { platform : [] for platform in platform_names }
    for root, dirs, files in os.walk(downloads_path):
        for file_name in files:
            #add to installer path
            installer_path = file_name
            for platform in platform_names:
                if platform in file_name \
                    or (platform == 'ps5' and ('ps5' in file_name or 'playstation-5' in file_name)) \
                    or (platform == 'ps4' and ('ps4' in file_name or 'playstation-4' in file_name)) \
                    or (platform == 'gdk' and 'game-core' in file_name):
                    installer_paths[platform].append(f'"{file_name}"')
                    break
            else:
                print(f'Couldn\'t find \"{platform}\" in {installer_path}! (case-sensitive)')

    #output add-on installer paths, RELATIVE to platform folder
    installer_dict = [ f'\"{plat_name}\" = @( {", ".join(plat_path)} )' for plat_name, plat_path in installer_paths.items() ]
    installer_dict = '@{ ' + '; '.join(installer_dict) + ' }'
    write_to_output('installer-dict', installer_dict)

    #check that versions line up  
    if unity_version is not None:
        if verbose: print('Validating add-on/installed unity versions.')
        os.chdir(downloads_path)
        for file_path in os.listdir():
            if 'unitysetup' not in file_path:
                continue

            #error handling for installer/unity version mismatch
            installer_name = PurePath(file_path).name
            installer_unity_version = installer_name.split('-')[6] #brittle, but whatever
            if installer_unity_version != unity_version:
                raise RuntimeError(f'Error: Mismatch between unity version ({unity_version}) and addon installer unity version ({installer_unity_version})!')

    #output directory that files were downloaded was saved to
    print('Done!')
