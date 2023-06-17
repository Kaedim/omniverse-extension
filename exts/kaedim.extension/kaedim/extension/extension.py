import omni.ext
import omni.ui as ui
import requests
import json
import urllib.request
import os
import omni.kit.commands
import omni.usd
from pxr import Sdf

# Any class derived from `omni.ext.IExt` in top level module (defined in `python.modules` of `extension.toml`) will be
# instantiated when extension gets enabled and `on_startup(ext_id)` will be called. Later when extension gets disabled
# on_shutdown() is called.
class KaedimExtensionExtension(omni.ext.IExt):
    # ext_id is current extension id. It can be used with extension manager to query additional information, like where
    # this extension is located on filesystem.

    def load_credentials(self):
        filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credentials.json')
        # Check if the file exists
        if os.path.isfile(filepath):
            # File exists, open it and try to read 'devID'
            with open(filepath, 'r') as file:
                data = json.load(file)
                self.devID = data.get('devID', None)
                self.apiKey = data.get('apiKey', None)
                self.refreshToken = data.get('refreshToken', None)
                self.jwt = data.get('jwt', None)
    
    def update_json_file(self, kv_pairs):
        filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credentials.json')
        data = {}
        if os.path.isfile(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)

        # Replace existing keys with new values, or add new keys
        for key, value in kv_pairs.items():
            data[key] = value

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)

    def login(self, devID, apiKey):
        url = "https://api.kaedim3d.com/api/v1/registerHook"
        payload = json.dumps({
            "devID": devID,
            "destination": "https://nvidia.kaedim3d.com/hook"
        })
        headers = {
            'X-API-Key': apiKey,
            'Content-Type': 'application/json'
        }
        response = requests.request("POST", url, headers=headers, data=payload)
        print(response.text)
        data = json.loads(response.text)
        if data["status"] == "success":
            self.jwt = data["jwt"]
            return True
        return False

    def refresh_jwt(self, devID, apiKey, rToken):
        print(devID, apiKey, rToken)
        url = "https://api.kaedim3d.com/api/v1/refreshJWT"
        payload = json.dumps({
            "devID": devID
        })
        headers = {
            'X-API-Key': apiKey,
            'refresh-token': rToken,
            'Content-Type': 'application/json'
        }
        response = requests.request("POST", url, headers=headers, data=payload)
        data = json.loads(response.text)
        print(data)
        if data["status"] == "success":
            print(data['jwt'])
            return data["jwt"]
        return None

    def login_panel(self, ext_id):  
        with self._window.frame:
            devID = ui.SimpleStringModel()
            apiKey = ui.SimpleStringModel()
            rToken = ui.SimpleStringModel()

            def on_connect():
                jwt = ''
                res = self.login(devID.as_string, apiKey.as_string)
                if res:
                    label.text = 'Successfully logged in'
                    jwt = self.refresh_jwt(devID.as_string, apiKey.as_string, rToken.as_string)
                if res and jwt is not None:
                    credentials = {
                        "devID" : devID.as_string,
                        "apiKey": apiKey.as_string,
                        "refreshToken": rToken.as_string,
                        "jwt": jwt
                    }
                    self.update_json_file(credentials) 
                    self.load_ui(ext_id)
                    label.text = 'Successfully logged in'
                else:
                    label.text = 'Oops! Something went wrong please try'
                
            with ui.VStack():
                ui.Label("Please enter your credentials:")
                ui.Spacer(height=10)
                ui.Label("DevID:")
                ui.Spacer(height=5)
                ui.StringField(model=devID, alignment=ui.Alignment.H_CENTER)
                ui.Spacer(height=10)
                ui.Label("Api-Key:")
                ui.Spacer(height=5)
                ui.StringField(model=apiKey, alignment=ui.Alignment.H_CENTER)
                ui.Spacer(height=10)
                ui.Label("Refresh-Token:")
                ui.Spacer(height=5)
                ui.StringField(model=rToken, alignment=ui.Alignment.H_CENTER)
                ui.Spacer(height=5)
                label = ui.Label("")
                ui.Spacer(height=10)
                ui.Button("Conect", clicked_fn=on_connect)  
    
    def asset_library(self, ext_id):
       
        def import_asset():
            asset = self.selected_asset
            if not asset or asset is None: return
            valid_iterations = [i for i in asset['iterations'] if i['status'] == 'completed' or i['status']=='uploaded']
            latest_version = max(valid_iterations, key=lambda x: x['iterationID'])
            results = latest_version['results']
            name = asset['image_tags'][0]
            requestID = asset['requestID']
            if type(results) == dict:
                file_path = check_and_download_file(requestID, results['obj'], 'obj')
                omni.kit.commands.execute("CreateReference",
                    path_to=Sdf.Path("/World/"+name), # Prim path for where to create the reference
                    asset_path=file_path, # The file path to reference. Relative paths are accepted too.
                    usd_context=omni.usd.get_context()
                )

        def fetch_assets():
            url = "https://api.kaedim3d.com/api/v1/fetchAll/?devID=b6ef2632-0625-490a-9876-fd852cfc6d33"
            payload = json.dumps({
                "devID": self.devID
            })
            headers = {
                'X-API-Key': self.apiKey,
                'Authorization': self.jwt,
                'Content-Type': 'application/json'
            }
            response = requests.request("GET", url, headers=headers, data=payload)

            jwt = ''
            if response.status_code == 401:
                self.jwt = self.refresh_jwt(self.devID, self.apiKey, self.refreshToken)
                headers["Authorization"] = self.jwt
                response = requests.request("GET", url, headers=headers, data=payload)
            if response.status_code == 200:
                if jwt:
                    credentials = {"jwt": self.jwt}
                    self.update_json_file(credentials)
                data = json.loads(response.text)
                assets = data["assets"]
                asset_library_ui(assets)
                if len(assets) <= 0:
                    print('No assets')
                else:
                    print('Ok')
            else:
                print('Error')
        
        def check_and_download_file(filename, url, filetype):
            # Make sure the folder path exists
            ext_manager = omni.kit.app.get_app().get_extension_manager()
            ext_path = ext_manager.get_extension_path(ext_id)
            folder_path = ext_path + "/data"
            if not os.path.exists(folder_path):
                print(f"The folder {folder_path} does not exist.")
                return
            file_path = os.path.join(folder_path, filename + '.' + filetype)

            # # Check if the file exists
            if not os.path.isfile(file_path):
                # Download and save the file from the url
                try:
                    urllib.request.urlretrieve(url, file_path)
            #         print(f"File downloaded and saved as {filename} in the folder {folder_path}.")
                except Exception as e:
                    print(f"Error occurred while downloading the file: {e}")
            return file_path

        def select_asset(asset):
            self.selected_asset = asset

        def isCompleted(asset):
            completedIterations = [i for i in asset['iterations'] if i['status']=='completed' or i['status']=='uploaded']
            return len(completedIterations) > 0
        
        def logout():
            emptyCredentials = {'devID':'','apiKey':'','jwt':'','refreshToken':''}
            self.update_json_file(emptyCredentials) 
            self.login_panel(ext_id)
            

        def asset_library_ui(assets):
            self.selected_asset = None
            with self._window.frame:
                with ui.VStack():
                    with ui.HStack(height=20):
                        ui.Button('Refresh', height=20, clicked_fn=fetch_assets)
                        ui.Button('Logout', height=20, clicked_fn=logout)
                    with ui.ScrollingFrame():
                        with ui.Grid(ui.Direction(2), column_width=120, row_height=120):
                            for asset in assets:
                                url = asset['image'][0]
                                source_url = check_and_download_file(asset['requestID'], url, 'png')
                                name = asset['image_tags'][0]
                                completed = isCompleted(asset)
                                if not completed: name = name + '\n' + asset['iterations'][len(asset['iterations'])-1]['status']
                                ui.Button(name, enabled=completed, image_url=source_url, clicked_fn=lambda asset=asset: select_asset(asset))
                    ui.Button('Import', height=20, clicked_fn=import_asset)

        fetch_assets() 

    def load_ui(self, ext_id):
        with self._window.frame:
            ui.Button('Load assets', clicked_fn=lambda ext_id=ext_id: self.asset_library(ext_id))
        
    def on_startup(self, ext_id):     
        self._window = ui.Window("Kaedim Extension", width=300, height=300)
        self.jwt = ''
        self.load_credentials()
        if not self.devID or not self.apiKey or not self.refreshToken:
            self.login_panel(ext_id)
        else:
            print('User already logged in', self.devID)
            self.asset_library(ext_id)

    def on_shutdown(self):

        print("kaedim extension shutdown")
        return
