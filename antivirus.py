import sys
import os
import shutil
import subprocess
import threading
from platform import system as system_platform
from platform import architecture
import re
import json
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog,
    QListWidget, QListWidgetItem, QHBoxLayout, QMessageBox, QCheckBox, QStackedWidget,
    QComboBox, QDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
import sklearn
import joblib
import pefile
import zipfile
import tarfile
import yara
import psutil
from notifypy import Notify
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from scapy.layers.inet import IP
from scapy.layers.inet6 import IPv6
from scapy.layers.dns import DNS, DNSQR, DNSRR
from scapy.all import sniff
sys.modules['sklearn.externals.joblib'] = joblib
# Set script directory
script_dir = os.getcwd()

# Configure logging
log_directory = os.path.join(script_dir, "log")  # Replace with the path to your log directory
log_file = os.path.join(log_directory, "scan_directory.log")

if not os.path.exists(log_directory):
    os.makedirs(log_directory)

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# Path to the config folder
config_folder_path = os.path.join(script_dir, "config")
if not os.path.exists(config_folder_path):
    os.makedirs(config_folder_path)

user_preference_file = os.path.join(config_folder_path, "user_preference.json")
quarantine_file_path = os.path.join(config_folder_path, "quarantine.json")
IP_ADDRESSES_PATH = os.path.join(script_dir, "website", "IP_Addresses.txt")
IPV6_ADDRESSES_PATH = os.path.join(script_dir, "website", "ipv6.txt")
DOMAINS_PATH = os.path.join(script_dir, "website", "Domains.txt")
ip_addresses_signatures_data = {}
ipv6_addresses_signatures_data = {}
domains_signatures_data = {}
# Get the root directory of the system drive based on the platform
if system_platform() == 'Windows':
    system_drives = [drive.mountpoint for drive in psutil.disk_partitions()]
    if system_drives:
        folder_to_watch = system_drives
    else:
        folder_to_watch = os.path.expandvars("%systemdrive%")  # Default to %systemdrive% if no drives are detected
elif system_platform() in ['Linux', 'FreeBSD', 'Darwin']:
    folder_to_watch = "/"     # Root directory on Linux, FreeBSD, and macOS
else:
    folder_to_watch = "/"     # Default to root directory on other platforms

def activate_uefi_drive():
    # Check if the platform is Windows
    if system_platform() == 'Windows':
        mount_command = 'mountvol X: /S'  # Command to mount UEFI drive
        try:
            # Execute the mountvol command
            subprocess.run(mount_command, shell=True, check=True)
            print("UEFI drive activated!")
        except subprocess.CalledProcessError as e:
            print(f"Error mounting UEFI drive: {e}")
    else:
        print("You are not in the Windows. No need to mountvol X: /S")

# Call the UEFI function
activate_uefi_drive()

def save_preferences(preferences):
    with open(user_preference_file, 'w') as f:
        json.dump(preferences, f, indent=4)

def load_quarantine_data():
    if os.path.exists(quarantine_file_path):
        with open(quarantine_file_path, 'r') as f:
            data = json.load(f)
            # Ensure the data is a list
            if isinstance(data, list):
                return data
            else:
                return []
    else:
        # If the file doesn't exist, create it with an empty list
        with open(quarantine_file_path, 'w') as f:
            json.dump([], f)
        return []

quarantine_data = load_quarantine_data()
def save_quarantine_data(quarantine_data):
    with open(quarantine_file_path, 'w') as f:
        json.dump(quarantine_data, f, indent=4)

def quarantine_file(file_path, virus_name):
    quarantine_folder = os.path.abspath(os.path.join(os.getcwd(), "quarantine"))
    if not os.path.exists(quarantine_folder):
        os.makedirs(quarantine_folder)
    try:
        # Extract the filename from the file_path
        filename = os.path.basename(file_path)
        # Create the destination path in the quarantine folder
        destination_path = os.path.join(quarantine_folder, filename)
        # Move the file to the quarantine folder
        shutil.move(file_path, destination_path)
        # Store the original file path in the quarantine data
        original_path = os.path.abspath(file_path)
        # Update the quarantine_data list with the new quarantine entry
        quarantine_data.append({"original_path": original_path, "quarantine_path": destination_path, "virus_name": virus_name})
        # Save the updated quarantine data
        save_quarantine_data(quarantine_data)
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to quarantine file: {str(e)}")

def extract_infos(file_path, rank=None):
    """Extract information about file"""
    file_name = os.path.basename(file_path)
    if rank is not None:
        return {'file_name': file_name, 'numeric_tag': rank}
    else:
        return {'file_name': file_name}

def extract_numeric_features(file_path, rank=None):
    """Extract numeric features of a file using pefile"""
    res = {}
    try:
        pe = pefile.PE(file_path)
        res['SizeOfOptionalHeader'] = pe.FILE_HEADER.SizeOfOptionalHeader
        res['MajorLinkerVersion'] = pe.OPTIONAL_HEADER.MajorLinkerVersion
        res['MinorLinkerVersion'] = pe.OPTIONAL_HEADER.MinorLinkerVersion
        res['SizeOfCode'] = pe.OPTIONAL_HEADER.SizeOfCode
        res['SizeOfInitializedData'] = pe.OPTIONAL_HEADER.SizeOfInitializedData
        res['SizeOfUninitializedData'] = pe.OPTIONAL_HEADER.SizeOfUninitializedData
        res['AddressOfEntryPoint'] = pe.OPTIONAL_HEADER.AddressOfEntryPoint
        res['BaseOfCode'] = pe.OPTIONAL_HEADER.BaseOfCode
        res['BaseOfData'] = pe.OPTIONAL_HEADER.BaseOfData if hasattr(pe.OPTIONAL_HEADER, 'BaseOfData') else 0
        res['ImageBase'] = pe.OPTIONAL_HEADER.ImageBase
        res['SectionAlignment'] = pe.OPTIONAL_HEADER.SectionAlignment
        res['FileAlignment'] = pe.OPTIONAL_HEADER.FileAlignment
        res['MajorOperatingSystemVersion'] = pe.OPTIONAL_HEADER.MajorOperatingSystemVersion
        res['MinorOperatingSystemVersion'] = pe.OPTIONAL_HEADER.MinorOperatingSystemVersion
        res['MajorImageVersion'] = pe.OPTIONAL_HEADER.MajorImageVersion
        res['MinorImageVersion'] = pe.OPTIONAL_HEADER.MinorImageVersion
        res['MajorSubsystemVersion'] = pe.OPTIONAL_HEADER.MajorSubsystemVersion
        res['MinorSubsystemVersion'] = pe.OPTIONAL_HEADER.MinorSubsystemVersion
        res['SizeOfImage'] = pe.OPTIONAL_HEADER.SizeOfImage
        res['SizeOfHeaders'] = pe.OPTIONAL_HEADER.SizeOfHeaders
        res['CheckSum'] = pe.OPTIONAL_HEADER.CheckSum
        res['Subsystem'] = pe.OPTIONAL_HEADER.Subsystem
        res['DllCharacteristics'] = pe.OPTIONAL_HEADER.DllCharacteristics
        res['SizeOfStackReserve'] = pe.OPTIONAL_HEADER.SizeOfStackReserve
        res['SizeOfStackCommit'] = pe.OPTIONAL_HEADER.SizeOfStackCommit
        res['SizeOfHeapReserve'] = pe.OPTIONAL_HEADER.SizeOfHeapReserve
        res['SizeOfHeapCommit'] = pe.OPTIONAL_HEADER.SizeOfHeapCommit
        res['LoaderFlags'] = pe.OPTIONAL_HEADER.LoaderFlags
        res['NumberOfRvaAndSizes'] = pe.OPTIONAL_HEADER.NumberOfRvaAndSizes
        if rank is not None:
            res['numeric_tag'] = rank
    except Exception as e:
        print(f"An error occurred while processing {file_path}: {e}")

    return res

def calculate_similarity(features1, features2, threshold=0.86):
    """Calculate similarity between two dictionaries of features"""
    common_keys = set(features1.keys()) & set(features2.keys())
    matching_keys = sum(1 for key in common_keys if features1[key] == features2[key])
    similarity = matching_keys / max(len(features1), len(features2))
    return similarity

def load_preferences():
    if os.path.exists(user_preference_file):
        with open(user_preference_file, 'r') as f:
            return json.load(f)
    else:
        default_preferences = {
            "use_machine_learning": True,
            "use_clamav": True,
            "use_yara": True,
            "real_time_protection": False,
            "real_time_web_protection": False,
            "enable_hips": True,
            "check_valid_signature": False,  # Add new preference for valid signature
            "check_microsoft_signature": False  # Add new preference for Microsoft signature
        }
        save_preferences(default_preferences)
        return default_preferences

preferences = load_preferences()
malicious_file_names = os.path.join(script_dir, "machinelearning", "malicious_file_names.json")
malicious_numeric_features = os.path.join(script_dir, "machinelearning", "malicious_numeric.pkl")
benign_numeric_features = os.path.join(script_dir, "machinelearning", "benign_numeric.pkl")
yara_folder_path = os.path.join(script_dir, "yara")
excluded_rules_dir = os.path.join(script_dir, "excluded")
excluded_rules_path = os.path.join(excluded_rules_dir, "excluded_rules.txt")

# Load excluded rules from text file
with open(excluded_rules_path, "r") as file:
        excluded_rules = file.read()
        print("YARA Excluded Rules Definitions loaded!")

# Load malicious file names from JSON file
with open(malicious_file_names, 'r') as f:
    malicious_file_names = json.load(f)
    print("Machine Learning Definitions loaded!")

# Load malicious numeric features from pickle file
with open(malicious_numeric_features, 'rb') as f:
    malicious_numeric_features = joblib.load(f)
    print("Malicious Feature Signatures loaded!")

# Load benign numeric features from pickle file
with open(benign_numeric_features, 'rb') as f:
    benign_numeric_features = joblib.load(f)
    print("Benign Feature Signatures loaded!")

print("Machine Learning AI Signatures loaded!")

try:
    # Load the precompiled rules from the .yrc file
    compiled_rule = yara.load(os.path.join(yara_folder_path, "compiled_rule.yrc"))
    pyas_rule = yara.load(os.path.join(yara_folder_path, "PYAS.yrc"))
    print("YARA Rules Definitions loaded!")
except yara.Error as e:
    print(f"Error loading precompiled YARA rule: {e}")

def load_data():
    try:
        # Load IPv4 addresses
        with open(IP_ADDRESSES_PATH, 'r') as ip_file:
            ip_addresses = ip_file.read().splitlines()
            ip_addresses_signatures_data = {ip: "" for ip in ip_addresses}

        # Load IPv6 addresses
        with open(IPV6_ADDRESSES_PATH, 'r') as ipv6_file:
            ipv6_addresses = ipv6_file.read().splitlines()
            ipv6_addresses_signatures_data = {ipv6: "" for ipv6 in ipv6_addresses}

        print("IP Addresses (ipv4, ipv6) loaded successfully!")
    except Exception as e:
        print(f"Error loading IP Addresses: {e}")

    try:
        # Load domains
        with open(DOMAINS_PATH, 'r') as domains_file:
            domains = domains_file.read().splitlines()
            domains_signatures_data = {domain: "" for domain in domains}
        print("Domains loaded successfully!")
    except Exception as e:
        print(f"Error loading Domains from {DOMAINS_PATH}: {e}")

    print("Domain and IPv4 IPv6 signatures loaded successfully!")

def hasMicrosoftSignature(path):
    try:
        if system_platform() == 'Windows':
            command = f"Get-AuthenticodeSignature '{path}' | Format-List"
            result = subprocess.run(["powershell.exe", "-Command", command], capture_output=True, text=True)
            if "O=Microsoft Corporation" in result.stdout:
                return True
            else:
                return False
        elif system_platform() == 'Darwin':  # macOS
            result = subprocess.run(["codesign", "-dvv", path], capture_output=True, text=True)
            if "Authority=Microsoft Corporation" in result.stdout:
                return True
            else:
                return False
        elif system_platform() == 'Linux':
            result = subprocess.run(["osslsigncode", "verify", "-in", path], capture_output=True, text=True)
            if "Microsoft Corporation" in result.stdout:
                return True
            else:
                return False
        else:
            print("Unsupported platform")
            return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False

def valid_signature_exists(file_path):    
    if system_platform() == 'Windows':
        return check_windows_signature(file_path)
    elif system_platform() == 'Darwin':  # macOS
        return check_macos_signature(file_path)
    elif system_platform() == 'Linux':
        return check_linux_signature(file_path)
    else:
        logging.error(f"Unsupported platform: {system_platform}")
        return True

def check_windows_signature(file_path):
    try:
        # Construct the command to get the Authenticode signature status
        command = f"(Get-AuthenticodeSignature '{file_path}').Status"
        result = subprocess.run(["powershell.exe", "-Command", command], capture_output=True, text=True)
        if "NotTrusted" in result.stdout or "HashMismatch" in result.stdout or "UnknownError" in result.stdout:
            return False
        else:
            return True
    except Exception as e:
        logging.error(f"Error checking Windows signature: {e}")
        return False

def check_windows_signature(file_path):
    try:
        command = f"Get-AuthenticodeSignature '{file_path}' | Format-List"
        result = subprocess.run(["powershell.exe", "-Command", command], capture_output=True, text=True)
        if "NotTrusted" in result.stdout and "HashMismatch" and "UnknownError" in result.stdout:
            return False
        else:
            return True
    except Exception as e:
        logging.error(f"Error checking Windows signature: {e}")
        return False

def check_macos_signature(file_path):
    try:
        result = subprocess.run(["codesign", "--verify", "--verbose=2", file_path], capture_output=True, text=True)
        if "succeeded" in result.stdout:
            return True
        elif "code object is not signed at all" in result.stdout:
            # If there's no signature, don't flag as malware
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Error checking macOS signature: {e}")
        return False

def check_linux_signature(file_path):
    try:
        result = subprocess.run(["osslsigncode", "verify", "-in", file_path], capture_output=True, text=True)
        if "Signature verified successfully" in result.stdout:
            return True
        elif "no signature found" in result.stdout:
            # If there's no signature, don't flag as malware
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Error checking Linux signature: {e}")
        return False

# Add the setup MBRFilter button function
def setup_mbrfilter():
    if system_platform() != 'Windows':
        QMessageBox.warning(None, "Unsupported Platform", "MBRFilter setup is only supported on Windows.")
        return
    
    # Check system architecture
    arch = architecture()[0]
    if arch == '64bit':
        mbrfilter_path = os.path.join(script_dir, "mbrfilter", "x64", "MBRFilter.inf")
    else:
        mbrfilter_path = os.path.join(script_dir, "mbrfilter", "x86", "MBRFilter.inf")

    if os.path.exists(mbrfilter_path):
        try:
            # Run infdefaultinstall.exe to setup MBRFilter
            result = subprocess.run(["infdefaultinstall.exe", mbrfilter_path], capture_output=True, text=True, check=True)
            QMessageBox.information(None, "Success", "MBRFilter has been setup successfully.")
        except subprocess.CalledProcessError as e:
            error_message = e.stderr if e.stderr else str(e)
            if "dijital imza" in error_message or "digital signature" in error_message:
                error_message += "\n\nThe INF file does not contain a digital signature, which is required for 64-bit Windows."
            QMessageBox.critical(None, "Error", f"Failed to setup MBRFilter: {error_message}")
    else:
        QMessageBox.critical(None, "Error", f"MBRFilter.inf not found at {mbrfilter_path}.")
        
def safe_remove(file_path):
    try:
        os.remove(file_path)
        print(f"File {file_path} deleted successfully.")
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")

def scan_file_with_machine_learning_ai(file_path, threshold=0.86):
    """Scan a file for malicious activity using machine learning."""
    try:
        # Initialize default response
        malware_definition = "Benign"
        
        # Load PE file
        try:
            pe = pefile.PE(file_path)
        except pefile.PEFormatError:
            return False, malware_definition

        # Extract features
        file_info = extract_infos(file_path)
        file_numeric_features = extract_numeric_features(file_path)

        is_malicious = False
        malware_rank = None
        nearest_malicious_similarity = 0
        nearest_benign_similarity = 0

        # Compare with malicious features
        for malicious_features, info in zip(malicious_numeric_features, malicious_file_names):
            rank = info['numeric_tag']
            similarity = calculate_similarity(file_numeric_features, malicious_features)
            if similarity > nearest_malicious_similarity:
                nearest_malicious_similarity = similarity
            if similarity >= threshold:
                is_malicious = True
                malware_rank = rank
                malware_definition = info['file_name']
                break

        # Compare with benign features
        for benign_features in benign_numeric_features:
            similarity = calculate_similarity(file_numeric_features, benign_features)
            if similarity > nearest_benign_similarity:
                nearest_benign_similarity = similarity

        # Determine final verdict
        if is_malicious:
            if nearest_benign_similarity >= 0.9:
                return False, malware_definition
            else:
                return True, malware_definition
        else:
            return False, malware_definition

    except Exception as e:
        print(f"An error occurred while scanning file {file_path}: {e}")
        return False, str(e)

def is_clamd_running():
    """Check if clamd is running."""
    if system_platform() in ['Linux', 'Darwin', 'FreeBSD']:
        result = subprocess.run(['pgrep', 'clamd'], capture_output=True, text=True)
        return result.returncode == 0
    elif system_platform() == 'Windows':
        result = subprocess.run(['sc', 'query', 'clamd'], capture_output=True, text=True)
        return "RUNNING" in result.stdout
    return False  # Unsupported platform

def start_clamd():
    """Start clamd service based on the platform."""
    if system_platform() == 'Windows':
        subprocess.run(["net", "start", "clamd"], shell=True)
    elif system_platform() in ['Linux', 'Darwin']:
        subprocess.run(["clamd"], shell=True)
    elif system_platform() == 'FreeBSD':
        subprocess.run(["service", "clamd", "start"])
    else:
        print("Unsupported platform for ClamAV")
        
def scan_file_with_clamd(file_path):
    """Scan file using clamd."""
    file_path = os.path.abspath(file_path)  # Get absolute path
    if not is_clamd_running():
        start_clamd()  # Start clamd if it's not running

    result = subprocess.run(["clamdscan", file_path], capture_output=True)
    clamd_output = result.stdout.decode('utf-8')  # Decode bytes to string
    print(f"Clamdscan output: {clamd_output}")

    if "ERROR" in clamd_output:
        print(f"Clamdscan reported an error: {clamd_output}")
        return "Clean"
    elif "FOUND" in clamd_output:
        match = re.search(r": (.+) FOUND", clamd_output)
        if match:
            virus_name = match.group(1).strip()
            return virus_name
    elif "OK" in clamd_output or "Infected files: 0" in clamd_output:
        return "Clean"
    else:
        print(f"Unexpected clamdscan output: {clamd_output}")
        return "Clean"

def kill_malicious_process(file_path):
    try:
        process_list = psutil.process_iter()
        for process in process_list:
            try:
                process_exe = process.exe()
                if process_exe and file_path == process_exe:
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        print(f"Error while terminating malicious process: {e}")

# Initialize the stop monitoring flag and preferences
stop_monitoring = False

def monitor_preferences():
    global stop_monitoring
    while not stop_monitoring:
        if preferences["real_time_protection"] and not real_time_observer.is_started:
            real_time_observer.start()
            print("Real-time protection is now enabled.")
        
        elif not preferences["real_time_protection"] and real_time_observer.is_started:
            real_time_observer.stop()
            print("Real-time protection is now disabled.")

stop_monitoring_for_web = False

def monitor_web_preferences():
    global stop_monitoring_for_web
    while not stop_monitoring_for_web:
        if preferences["real_time_web_protection"] and not real_time_web_observer.is_started:
            real_time_web_observer.start()
            print("Real-time web protection is now enabled.")

        elif not preferences["real_time_web_protection"] and real_time_web_observer.is_started:
            real_time_web_observer.stop()
            print("Real-time web protection is now disabled.")

stop_monitoring_for_snort = False

def monitor_snort_preferences():
    global stop_monitoring_for_snort
    while not stop_monitoring_for_snort:
        # Check preferences and control Snort accordingly
        if preferences["enable_hips"] and not snort_observer.is_started:
            snort_observer.start()
            print("Snort is now enabled.")

        elif not preferences["enable_hips"] and snort_observer.is_started:
            snort_observer.stop()
            print("Snort is now disabled.")

def scan_file_real_time(file_path):
    """Scan file in real-time using multiple engines."""
    logging.info(f"Started scanning file: {file_path}")

    if not os.path.exists(file_path):
        logging.error(f"File does not exist: {file_path}")
        return False, "Clean"
    else:
        # Check for valid signature
        if preferences.get("check_valid_signature", False):
            if not valid_signature_exists(file_path):
                logging.warning(f"Invalid signature detected: {file_path}")
                return True, "Invalid Signature"
            else:
                # Check for Microsoft signature only if the signature is valid
                if preferences.get("check_microsoft_signature", False) and hasMicrosoftSignature(file_path):
                    logging.info(f"File signed by Microsoft, skipping: {file_path}")
                    return False, "Clean"
                else:
                    # Check with ClamAV if enabled
                    if preferences.get("use_clamav", False):
                        result = scan_file_with_clamd(file_path)
                        if result and result != "Clean" and result != "":
                            logging.warning(f"Infected file detected (ClamAV): {file_path} - Virus: {result}")
                            return True, result
                    # Check with YARA if enabled
                    if preferences.get("use_yara", False):
                        try:
                            yara_result = yara_scanner.static_analysis(file_path)
                            if yara_result and yara_result != "Clean" and yara_result != "":
                                logging.warning(f"Infected file detected (YARA): {file_path} - Virus: {yara_result}")
                                return True, yara_result
                        except PermissionError as e:
                            logging.error(f"Permission denied: {file_path} - {str(e)}")
                            return False, "Clean"
                        except Exception as e:
                            logging.error(f"Error scanning file with YARA: {file_path} - {str(e)}")
                            return False, "Clean"
                    
                    # Check with machine learning if enabled
                    if preferences.get("use_machine_learning", False):
                        is_malicious, malware_definition = scan_file_with_machine_learning_ai(file_path)
                        if is_malicious and malware_definition != "Clean" and malware_definition != "":
                            logging.warning(f"Infected file detected (ML): {file_path} - Virus: {malware_definition}")
                            return True, malware_definition

                    # Check if the file is a PE file (executable)
                    if is_pe_file(file_path):
                        scan_result, virus_name = scan_pe_file(file_path)
                        if scan_result and virus_name != "Clean" and virus_name != "":
                            logging.warning(f"Infected file detected (PE): {file_path} - Virus: {virus_name}")
                            return True, virus_name

                    # Check if the file is a tar archive
                    if tarfile.is_tarfile(file_path):
                        scan_result, virus_name = scan_tar_file(file_path)
                        if scan_result and virus_name != "Clean" and virus_name != "":
                            logging.warning(f"Infected file detected (TAR): {file_path} - Virus: {virus_name}")
                            return True, virus_name

                    # Check if the file is a zip archive
                    if zipfile.is_zipfile(file_path):
                        scan_result, virus_name = scan_zip_file(file_path)
                        if scan_result and virus_name != "Clean" and virus_name != "":
                            logging.warning(f"Infected file detected (ZIP): {file_path} - Virus: {virus_name}")
                            return True, virus_name

        # If all checks are passed and the file is clean
        logging.info(f"File is clean: {file_path}")
        return False, "Clean"
        
def scan_sub_file_real_time(data):
    """Scan sub-files (extracted from PE, TAR, ZIP) in real-time using multiple engines."""

    try:
        # Check if it's a PE file
        try:
            pe = pefile.PE(data=data)
            scan_result, virus_name = scan_pe_file(data)
            if scan_result:
                return True, virus_name
        except pefile.PEFormatError:
            pass

        # Check if it's a ZIP file
        try:
            zfile = zipfile.ZipFile(data)
            scan_result, virus_name = scan_zip_file(data)
            if scan_result:
                return True, virus_name
        except zipfile.BadZipFile:
            pass

        # Check if it's a TAR file
        try:
            tar = tarfile.open(fileobj=data, mode='r')
            scan_result, virus_name = scan_tar_file(data)
            if scan_result:
                return True, virus_name
        except tarfile.ReadError:
            pass

        # Check with ClamAV if enabled and no issues found
        if preferences.get("use_clamav", False):
            clamav_result = scan_file_with_clamd(data)
            if clamav_result and clamav_result != "Clean" and clamav_result != "":
                logging.warning(f"Infected sub-file detected (ClamAV): Virus: {clamav_result}")
                return True, clamav_result

        # Check with YARA if enabled and no issues found
        if preferences.get("use_yara", False):
            try:
                yara_result = yara_scanner.static_analysis(data)
                if yara_result and yara_result != "Clean" and yara_result != "":
                    logging.warning(f"Infected sub-file detected (YARA): Virus: {yara_result}")
                    return True, yara_result
            except PermissionError as e:
                logging.error(f"Permission denied: {str(e)}")
            except Exception as e:
                logging.error(f"Error scanning sub-file with YARA: {str(e)}")

        # Check with machine learning if enabled and no issues found
        if preferences.get("use_machine_learning", False):
            is_malicious, malware_definition = scan_file_with_machine_learning_ai(data)
            if is_malicious and malware_definition != "Clean" and malware_definition != "":
                logging.warning(f"Infected sub-file detected (ML): Virus: {malware_definition}")
                return True, malware_definition

        # Check for valid signature
        if preferences.get("check_valid_signature", False):
            if not valid_signature_exists(data):
                logging.warning(f"Invalid signature detected for sub-file.")
                return True, "Invalid Signature"

        # Check for Microsoft signature only if the signature is valid
        if preferences.get("check_microsoft_signature", False):
            if hasMicrosoftSignature(data):
                logging.info(f"Sub-file signed by Microsoft, skipping.")
                return False, "Clean"

        # If no malware found, return False indicating the file is clean
        return False, "Clean"

    except Exception as e:
        logging.error(f"Error scanning sub-file in real-time: {str(e)}")
        return False, "Clean"

def is_pe_file(file_path):
    """Check if the file is a PE file (executable)."""
    try:
        pe = pefile.PE(file_path)
        return True
    except pefile.PEFormatError:
        return False

def scan_pe_file(file_path):
    """Scan files within a PE file."""
    virus_name = []
    try:
        # Load the PE file
        pe = pefile.PE(file_path)

        # Extract resources
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if hasattr(entry, 'directory'):
                for resource in entry.directory.entries:
                    if hasattr(resource, 'directory'):
                        for res in resource.directory.entries:
                            if hasattr(res, 'directory'):
                                for r in res.directory.entries:
                                    if hasattr(r, 'directory'):
                                        for rsrc in r.directory.entries:
                                            if hasattr(rsrc, 'data'):
                                                # Extract resource data
                                                data = pe.get_data(rsrc.data.struct.OffsetToData, rsrc.data.struct.Size)
                                                # Scan the extracted data
                                                scan_result, virus_name = scan_sub_file_real_time(data)
                                                if scan_result:
                                                    virus_name.append(virus_name)
                                                    break  # Stop scanning if malware is detected
                                        if virus_name:
                                            break
                                    if virus_name:
                                        break
                                if virus_name:
                                    break
                            if virus_name:
                                break
                        if virus_name:
                            break
                    if virus_name:
                        break
                if virus_name:
                    break
            if virus_name:
                break
    except Exception as e:
        logging.error(f"Error scanning exe file: {e}")

    if virus_name:
        return True, virus_name[0]  # Return the first virus name
    else:
        return False, ""

def scan_zip_file(file_path):
    """Scan files within a zip archive."""
    try:
        with zipfile.ZipFile(file_path, 'r') as zfile:
            virus_name = []
            for file_info in zfile.infolist():
                if not file_info.is_dir():
                    scan_result, virus_name = scan_sub_file_real_time(zfile.read(file_info.filename))
                    if scan_result:
                        virus_name.append(virus_name)
                        break  # Stop scanning if malware is detected
            if virus_name:
                return True, virus_name[0]  # Return the first virus name
    except Exception as e:
        logging.error(f"Error scanning zip file: {e}")
    return False, ""

def scan_tar_file(file_path):
    """Scan files within a tar archive."""
    try:
        tar = tarfile.TarFile(file_path)
        detected_virus_names = []
        for member in tar.getmembers():
            if member.isfile():
                file_object = tar.extractfile(member)
                if file_object:
                    file_data = file_object.read()
                    scan_result, virus_name = scan_sub_file_real_time(file_data)
                    if scan_result:
                        detected_virus_names.append(virus_name)
                        break  # Stop scanning if malware is detected
        tar.close()
        if detected_virus_names:
            return True, detected_virus_names[0]  # Return the first virus name
    except Exception as e:
        logging.error(f"Error scanning tar file: {e}")
    return False, ""

class Firewall:
    @staticmethod
    def add_rule(rule):
        try:
            if system_platform() == 'Windows':
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule", "name", f"Block {rule.remote_address}", "dir", "in", "action", "block", "remoteip", rule.remote_address], check=True)
                print(f"Blocking traffic from {rule.remote_address} using Windows Firewall")
            elif system_platform() == 'Darwin':
                subprocess.run(["pfctl", "-e"], check=True)
                subprocess.run(["pfctl", "-t", "blocklist", "-T", "add", rule.remote_address], check=True)
                print(f"Blocking traffic from {rule.remote_address} using pfctl on macOS")
            elif system_platform() == 'Linux':
                subprocess.run(["nft", "add", "rule", "ip", "filter", "input", "ip", "saddr", rule.remote_address, "drop"], check=True)
                print(f"Blocking traffic from {rule.remote_address} using nftables")
            elif system_platform() == 'FreeBSD':
                subprocess.run(["ipfw", "add", "deny", "ip", "from", rule.remote_address], check=True)
                print(f"Blocking traffic from {rule.remote_address} using ipfw on FreeBSD")
            else:
                print(f"Firewall is not supported on {system_platform}.")
        except subprocess.CalledProcessError as e:
            print(f"Error adding firewall rule: {e}")

class RealTimeWebProtectionHandler:
    def __init__(self):
        self.firewall = Firewall()

    def scan_domain(self, domain):
        print("Scanning domain:", domain)
        parts = domain.split(".")
        if len(parts) < 3:
            main_domain = domain
        else:
            main_domain = ".".join(parts[-2:])

        for parent_domain in domains_signatures_data:
            if main_domain == parent_domain or main_domain.endswith(f".{parent_domain}"):
                print(f"Main domain {main_domain} or its parent domain {parent_domain} matches the signatures.")
                notify_user_for_web(domain=main_domain)
                self.mark_packet_for_drop(main_domain)
                return

    def scan_ip_address(self, ip_address, is_ipv6=False):
        print("Scanning IP address:", ip_address)
        if is_ipv6 and ip_address in ipv6_addresses_signatures_data:
            print(f"IPv6 address {ip_address} matches the signatures.")
            notify_user_for_web(ip_address=ip_address)
            self.mark_packet_for_drop(ip_address)
        elif ip_address in ip_addresses_signatures_data:
            print(f"IPv4 address {ip_address} matches the signatures.")
            notify_user_for_web(ip_address=ip_address)
            self.mark_packet_for_drop(ip_address)

    def mark_packet_for_drop(self, identifier):
        try:
            self.firewall.add_rule(identifier)
            print(f"Blocking traffic for {identifier}")
        except Exception as e:
            print(f"Error setting firewall rule: {e}")

    def on_packet_received(self, packet):
        if IP in packet:
            self.handle_ipv4(packet)
        elif IPv6 in packet:
            self.handle_ipv6(packet)

    def handle_ipv4(self, packet):
        if DNS in packet:
            if packet[DNS].qd:
                for i in range(packet[DNS].qdcount):
                    query_name = packet[DNSQR][i].qname.decode().rstrip('.')
                    self.scan_domain(query_name)
                    print("DNS Query (IPv4):", query_name)
            if packet[DNS].an:
                for i in range(packet[DNS].ancount):
                    answer_name = packet[DNSRR][i].rrname.decode().rstrip('.')
                    self.scan_domain(answer_name)
                    print("DNS Answer (IPv4):", answer_name)

        # Scan IPv4 addresses
        self.scan_ip_address(packet[IP].src)
        self.scan_ip_address(packet[IP].dst)

    def handle_ipv6(self, packet):
        if DNS in packet:
            if packet[DNS].qd:
                for i in range(packet[DNS].qdcount):
                    query_name = packet[DNSQR][i].qname.decode().rstrip('.')
                    self.scan_domain(query_name)
                    print("DNS Query (IPv6):", query_name)
            if packet[DNS].an:
                for i in range(packet[DNS].ancount):
                    answer_name = packet[DNSRR][i].rrname.decode().rstrip('.')
                    self.scan_domain(answer_name)
                    print("DNS Answer (IPv6):", answer_name)

        # Scan IPv6 addresses
        self.scan_ip_address(packet[IPv6].src, is_ipv6=True)
        self.scan_ip_address(packet[IPv6].dst, is_ipv6=True)

class RealTimeWebProtectionObserver:
    def __init__(self):
        self.handler = RealTimeWebProtectionHandler()
        self.is_started = False
        self.thread = None

    def start(self):
        if not self.is_started:
            self.thread = threading.Thread(target=self.start_sniffing)
            self.thread.start()
            self.is_started = True
            print("Real-time web protection observer started")

    def stop(self):
        if self.is_started:
            self.thread.join()  # Wait for the thread to finish
            self.is_started = False
            print("Real-time web protection observer stopped")

    def start_sniffing(self):
        # Define a custom filter to exclude localhost and local IPs
        filter_expression = f"(tcp or udp)"
        sniff(filter=filter_expression, prn=self.handler.on_packet_received, store=0)

def notify_user_for_web(domain=None, ip_address=None):
    notification = Notify()
    notification.title = "Malware or Phishing Alert"
    if domain and ip_address:
        notification.message = f"Phishing or Malicious activity detected:\nDomain: {domain}\nIP Address: {ip_address}"
    elif domain:
        notification.message = f"Phishing or Malicious activity detected:\nDomain: {domain}"
    elif ip_address:
        notification.message = f"Phishing or Malicious activity detected:\nIP Address: {ip_address}"
    else:
        notification.message = "Phishing or Malicious activity detected"
    notification.send()

class RealTimeProtectionHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()

    def on_any_event(self, event):
        if event.is_directory:
            print(f"Folder changed: {event.src_path}")
            self.scan_folder_rtp(event.src_path)
        else:
            file_path = event.src_path
            if event.event_type == 'created':
                print(f"File created: {file_path}")
                self.scan_and_quarantine(file_path)
            elif event.event_type == 'modified':
                print(f"File modified: {file_path}")
                self.scan_and_quarantine(file_path)
            elif event.event_type == 'moved':
                src_path = event.src_path
                dest_path = event.dest_path
                print(f"File moved from {src_path} to {dest_path}")
                self.scan_and_quarantine(src_path)  # Scan the source path
                self.scan_and_quarantine(dest_path) # Scan the destination path

    def is_folder_in_use(self, folder_path):
        # Check if the folder is being used by any process
        for proc in psutil.process_iter(['pid', 'name', 'cwd']):
            try:
                if folder_path == proc.cwd():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False

    def scan_folder_rtp(self, folder_path):
        # Check if the folder is in use by any process
        if not self.is_folder_in_use(folder_path):
            return
        
        # Scan files that are not in use by any process
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        for file in files:
            file_path = os.path.join(folder_path, file)
            self.scan_and_quarantine(file_path)

    def scan_and_quarantine(self, file_path):
        print(f"Scanning file: {file_path}")
        is_malicious, virus_name = scan_file_real_time(file_path)
        if is_malicious:
            print(f"File {file_path} is malicious. Virus: {virus_name}")
            self.notify_user(file_path, virus_name)
            kill_malicious_process(file_path)
            # Quarantine the file in a separate thread
            quarantine_thread = threading.Thread(target=quarantine_file, args=(file_path, virus_name))
            quarantine_thread.start()
    def notify_user(self, file_path, virus_name):
        notification = Notify()
        notification.title = "Malware Alert"
        notification.message = f"Malicious file detected: {file_path}\nVirus: {virus_name}"
        notification.send()

class RealTimeProtectionObserver:
    def __init__(self, folder_to_watch):
        self.folder_to_watch = folder_to_watch
        self.event_handler = RealTimeProtectionHandler()
        self.observer = Observer()
        self.is_started = False  # Initialize is_started attribute
        self.is_initialized = False

    def start(self):
        self.check_folder_to_watch()  # Check and update folder_to_watch if necessary
        
        if not self.is_initialized:
            # Schedule the event handler for each drive
            for drive in psutil.disk_partitions():
                if os.path.isdir(drive.mountpoint):
                    self.observer.schedule(self.event_handler, path=drive.mountpoint, recursive=True)
            self.is_initialized = True
        
        if not self.is_started:
            self.observer.start()
            self.is_started = True
            print("Observer started")

    def stop(self):
        if self.is_started:
            self.observer.stop()
            self.observer.join()
            self.is_started = False
            print("Observer stopped")

    def check_folder_to_watch(self):
        if system_platform() == 'Windows':
            disk_partitions = [drive.mountpoint for drive in psutil.disk_partitions()]
            if self.folder_to_watch not in disk_partitions:
                print(f"Warning: {self.folder_to_watch} does not exist or is not accessible.")
                # Update folder_to_watch to monitor all accessible partitions
                accessible_partitions = [partition for partition in disk_partitions if os.path.isdir(partition)]
                if accessible_partitions:
                    self.folder_to_watch = accessible_partitions
                    print(f"Updated folder_to_watch to monitor all accessible partitions: {self.folder_to_watch}")
                else:
                    # If no accessible drives are found, set to %systemdrive%
                    self.folder_to_watch = [os.path.expandvars("%systemdrive%")]
                    print(f"No accessible drives found. Setting folder_to_watch to default: {self.folder_to_watch}")
            else:
                print(f"folder_to_watch is accessible: {self.folder_to_watch}")

class SnortObserver:
    def __init__(self):
        self.is_started = False
        self.thread = None
        self.snort_process = None

    def start_sniffing(self):
        max_device_number = 20
        for device_number in range(1, max_device_number + 1):
            try:
                if system_platform() == 'Windows':
                    snort_config_path = "C:\\Snort\\etc\\snort.conf"
                else:
                    snort_config_path = "/etc/snort/snort.conf"
                    
                self.snort_process = subprocess.Popen(
                    ["snort", "-i", str(device_number), "-c", snort_config_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                # Function to read and print stdout in real-time
                def read_stdout(pipe):
                    for output in iter(pipe.readline, b''):
                        print(output.decode('utf-8').strip())

                # Function to read and print stderr in real-time
                def read_stderr(pipe):
                    for error in iter(pipe.readline, b''):
                        print(error.decode('utf-8').strip())
                        # Check if the error is related to an invalid device number
                        if "ERROR: OpenPcap() device" in error.decode('utf-8').strip():
                            self.snort_process.terminate()
                            logging.error(f"Device number {device_number} is invalid. Snort process terminated.")
                            print(f"Device number {device_number} is invalid. Snort process terminated.")
                            return

                # Create and start threads for stdout and stderr
                stdout_thread = threading.Thread(target=read_stdout, args=(self.snort_process.stdout,))
                stderr_thread = threading.Thread(target=read_stderr, args=(self.snort_process.stderr,))
                
                stdout_thread.start()
                stderr_thread.start()

                stdout_thread.join()
                stderr_thread.join()

                # Check if there was an error related to an invalid device number
                if self.snort_process.returncode != 0:
                    logging.info(f"Device number {device_number} is invalid or another error occurred.")
                    print(f"Device number {device_number} is invalid or another error occurred.")
                    break
                else:
                    logging.info(f"Snort started on device number {device_number}.")
                    print(f"Snort started on device number {device_number}.")
                    continue
            except Exception as e:
                logging.error(f"Failed to start Snort on device {device_number}: {e}")
                print(f"Failed to start Snort on device {device_number}: {e}")
                break

    def start(self):
        if not self.is_started:
            self.thread = threading.Thread(target=self.start_sniffing)
            self.thread.start()
            self.is_started = True
            logging.info("Snort has been started.")
            print("Snort has been started.")

    def stop(self):
        if self.is_started and self.snort_process:
            self.snort_process.terminate()
            self.thread.join()  # Wait for the thread to finish
            self.is_started = False
            logging.info("Snort has been stopped.")
            print("Snort has been stopped.")

# Create the real-time observer with the system drive as the monitored directory
real_time_observer = RealTimeProtectionObserver(folder_to_watch)
real_time_web_observer = RealTimeWebProtectionObserver()
# Initialize Snort observer
snort_observer = SnortObserver()

class YaraScanner:
    def scan_data(self, file_path):
        matched_rules = []
        
        if os.path.exists(file_path):
            with open(file_path, 'rb') as file:
                data = file.read()
                
                # Check matches for compiled_rule
                if compiled_rule:
                    matches = compiled_rule.match(data=data)
                    if matches:
                        for match in matches:
                            if match.rule not in excluded_rules:
                                matched_rules.append(match.rule)
                        return matched_rules  # Return immediately if a match is found

                # Check matches for pyas_rule
                if pyas_rule:
                    matches = pyas_rule.match(data=data)
                    if matches:
                        for match in matches:
                            if match.rule not in excluded_rules:
                                matched_rules.append(match.rule)
                        return matched_rules  # Return immediately if a match is found

    def static_analysis(self, file_path):
        return self.scan_data(file_path)

yara_scanner = YaraScanner()

class ScanManager(QDialog):
    folder_scan_finished = Signal()
    memory_scan_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan Manager")
        self.setup_ui()
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.pause_event.set()

        # Initialize counters
        self.total_scanned = 0
        self.infected_files = 0
        self.clean_files = 0

    def setup_ui(self):
        main_layout = QVBoxLayout()

        self.pause_button = QPushButton("Pause Scan", self)
        self.pause_button.clicked.connect(self.pause_scanning)
        main_layout.addWidget(self.pause_button)

        self.stop_button = QPushButton("Stop Scan", self)
        self.stop_button.clicked.connect(self.stop_scanning)
        main_layout.addWidget(self.stop_button)

        self.resume_button = QPushButton("Resume Scan", self)
        self.resume_button.clicked.connect(self.resume_scanning)
        main_layout.addWidget(self.resume_button)

        self.quick_scan_button = QPushButton("Quick Scan")
        self.quick_scan_button.clicked.connect(self.quick_scan)
        main_layout.addWidget(self.quick_scan_button)

        self.full_scan_button = QPushButton("Full Scan")
        self.full_scan_button.clicked.connect(self.full_scan)
        main_layout.addWidget(self.full_scan_button)

        self.uefi_scan_button = QPushButton("UEFI Scan")
        self.uefi_scan_button.clicked.connect(self.uefi_scan)
        main_layout.addWidget(self.uefi_scan_button)

        self.scan_folder_button = QPushButton("Scan Folder")
        self.scan_folder_button.clicked.connect(self.scan_folder)
        main_layout.addWidget(self.scan_folder_button)

        self.scan_file_button = QPushButton("Scan File")
        self.scan_file_button.clicked.connect(self.scan_file)
        main_layout.addWidget(self.scan_file_button)

        self.scan_memory_button = QPushButton("Scan Memory")
        self.scan_memory_button.clicked.connect(self.scan_memory)
        main_layout.addWidget(self.scan_memory_button)

        self.detected_list_label = QLabel("Detected Threats:")
        main_layout.addWidget(self.detected_list_label)

        self.detected_list = QListWidget()
        main_layout.addWidget(self.detected_list)

        self.current_file_label = QLabel("Currently Scanning:")
        main_layout.addWidget(self.current_file_label)

        self.scanned_files_label = QLabel("Total Scanned Files: 0")
        main_layout.addWidget(self.scanned_files_label)

        self.infected_files_label = QLabel("Infected Files: 0")
        main_layout.addWidget(self.infected_files_label)

        self.clean_files_label = QLabel("Clean Files: 0")
        main_layout.addWidget(self.clean_files_label)

        self.action_button_layout = QHBoxLayout()

        self.quarantine_button = QPushButton("Quarantine")
        self.quarantine_button.clicked.connect(self.quarantine_selected)
        self.action_button_layout.addWidget(self.quarantine_button)

        self.skip_button = QPushButton("Skip")
        self.skip_button.clicked.connect(self.skip_selected)
        self.action_button_layout.addWidget(self.skip_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        self.action_button_layout.addWidget(self.delete_button)

        self.action_combobox = QComboBox()
        self.action_combobox.addItems(["Quarantine All", "Delete All", "Skip All"])
        self.action_button_layout.addWidget(self.action_combobox)

        self.apply_action_button = QPushButton("Apply Action")
        self.apply_action_button.clicked.connect(self.apply_action)
        self.action_button_layout.addWidget(self.apply_action_button)

        self.kill_button = QPushButton("Kill Malicious Processes")
        self.kill_button.clicked.connect(self.kill_all_malicious_processes)
        self.action_button_layout.addWidget(self.kill_button)

        main_layout.addLayout(self.action_button_layout)
        self.setLayout(main_layout)

    def reset_scan(self):
        self.total_scanned = 0
        self.infected_files = 0
        self.clean_files = 0
        self.update_scan_labels()
        self.detected_list.clear()
        self.current_file_label.setText("Currently Scanning:")

    def start_scan(self, path):
        self.thread = QThread()
        self.thread.run = lambda: self.scan(path)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        
    def scan_sub_file_path_classic(self, file_data):
        """Scan file data using various engines."""
        virus_name = ""

        if system_platform() in ['Windows', 'Linux', 'Darwin']:
            # Check for valid signature
            if preferences.get("check_valid_signature", False):
                if not self.valid_signature_exists(file_data):
                    logging.warning("Invalid signature detected")
                    virus_name = "Invalid Signature"
                    return True, virus_name
                
                # Check for Microsoft signature only if the signature is valid
                if preferences.get("check_microsoft_signature", False):
                    if self.hasMicrosoftSignature(file_data):
                        logging.info("File signed by Microsoft, skipping")
                        return False, ""
            
            # Check with ClamAV if enabled and no issues found
            if preferences.get("use_clamav", False):
                virus_name = scan_file_with_clamd(file_data)
                if virus_name:
                    logging.warning(f"Infected file detected - Virus: {virus_name}")
                    return True, virus_name

            # Check with YARA if enabled and no issues found
            if preferences.get("use_yara", False):
                yara_result = yara_scanner.scan_data(file_data)
                if yara_result:
                    if isinstance(yara_result, list):
                        virus_name = ', '.join(yara_result)
                    elif isinstance(yara_result, str):
                        virus_name = yara_result
                    logging.warning(f"Infected file detected - Virus: {virus_name}")
                    return True, virus_name

        # If no malware found, return False indicating the file is clean
        logging.info("File is clean")
        return False, ""

    def scan(self, path):
        if os.path.isdir(path):
            self.scan_directory(path)
        else:
            self.scan_file_path(path)
        self.folder_scan_finished.emit()

    def get_uefi_folder(self):
        if system_platform() == 'Windows':
            return "X:\\"
        else:
            return "/boot/efi" if system_platform() in ['Linux', 'FreeBSD', 'Darwin'] else "/boot/efi"
    
    def scan_memory(self):
        self.reset_scan()

        def scan():
            scanned_files = set()  # Set to store scanned file paths
            detected_files = []

            try:
                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                    try:
                        process_name = proc.info['name']
                        executable_path = proc.info['exe']
                        # Check if the process has an executable path
                        if executable_path and executable_path not in scanned_files:
                            detected_files.append(executable_path)
                            scanned_files.add(executable_path)  # Add path to scanned files set
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                        print(f"Error while accessing process info: {e}")
            except Exception as e:
                print(f"Error while iterating over processes: {e}")

            # Send detected memory file paths for scanning
            with ThreadPoolExecutor(max_workers=1000) as executor:
                for file_path in detected_files:
                    executor.submit(self.scan_file_path, file_path)

            # Emit the signal when the memory scan is finished
            self.memory_scan_finished.emit()

        # Start the scan in a separate thread
        threading.Thread(target=scan).start()

    def scan_directory(self, directory):
        detected_threats = []
        clean_files = []

        def scan_file(file_path):
            if self.pause_event.is_set():
                logging.info("Scanning paused. Waiting for resume.")
                self.pause_event.wait()
            if self.stop_event.is_set():
                logging.info("Scanning stopped.")
                return

            with ThreadPoolExecutor(max_workers=1000) as executor:
                future = executor.submit(self.scan_file_path, file_path)
                is_infected, virus_name = future.result()

            if is_infected:
                # If the file is infected, add it to the detected list
                item = QListWidgetItem(f"Scanned file: {file_path} - Virus: {virus_name}")
                item.setData(Qt.UserRole, file_path)
                detected_threats.append((file_path, virus_name))
            else:
                clean_files.append(file_path)

        with ThreadPoolExecutor(max_workers=1000) as executor:
            futures = []
            for root, _, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    futures.append(executor.submit(scan_file, file_path))

            # Ensure all futures are completed
            for future in as_completed(futures):
                future.result()

        self.show_summary(detected_threats, clean_files)
        self.folder_scan_finished.emit()

    def show_summary(self, detected_threats, clean_files):
        num_detected = len(detected_threats)
        num_clean = len(clean_files)
        total_files = num_detected + num_clean

        logging.info(f"----------- SCAN SUMMARY -----------")
        logging.info(f"Infected files: {num_detected}")
        logging.info(f"Clean files: {num_clean}")
        logging.info(f"Total files scanned: {total_files}")
        logging.info("-----------------------------------")

    def is_pe_file_classic(self, file_path):
        """Check if the file is a PE file (executable)."""
        try:
            pe = pefile.PE(file_path)
            return True
        except pefile.PEFormatError:
            return False
    
    def scan_pe_file_classic(self, file_path):
        """Scan PE file for viruses."""
        virus_name = ""
        try:
            pe = pefile.PE(file_path)
            # Add virus scanning logic here
            return True, virus_name  # Modify this logic based on actual scanning
        except Exception as e:
            print(f"Error scanning PE file: {e}")
            return False, ""

    def is_tar_file_classic(self, file_path):
        """Check if the file is a tar archive."""
        return tarfile.is_tarfile(file_path)

    def scan_tar_file_classic(self, file_path):
        """Scan files within a tar archive."""
        try:
            tar = tarfile.TarFile(file_path)
            detected_virus_names = []
            for member in tar.getmembers():
                if member.isfile():
                    file_object = tar.extractfile(member)
                    if file_object:
                        file_data = file_object.read()
                        scan_result, virus_name = self.scan_sub_file_path_classic(file_data)
                        if scan_result:
                            detected_virus_names.append(virus_name)
                            break  # Stop scanning if malware is detected
            tar.close()
            if detected_virus_names:
                return True, detected_virus_names[0]  # Return the first virus name
        except Exception as e:
            print(f"Error scanning tar file: {e}")
        return False, ""

    def is_zip_file_classic(self, file_path):
        """Check if the file is a zip archive."""
        return zipfile.is_zipfile(file_path)

    def scan_zip_file_classic(self, file_path):
        """Scan files within a zip archive."""
        try:
            with zipfile.ZipFile(file_path, 'r') as zfile:
                detected_virus_names = []
                for file_info in zfile.infolist():
                    if not file_info.is_dir():
                        file_data = zfile.read(file_info.filename)
                        scan_result, virus_name = self.scan_sub_file_path_classic(file_data)
                        if scan_result:
                            detected_virus_names.append(virus_name)
                            break  # Stop scanning if malware is detected
                if detected_virus_names:
                    return True, detected_virus_names[0]  # Return the first virus name
        except Exception as e:
            print(f"Error scanning zip file: {e}")
        return False, ""

    def full_scan(self):
        if self.system_platform() == 'nt':  # Windows platform
            disk_partitions = [drive.mountpoint for drive in psutil.disk_partitions()]
            for drive in disk_partitions:
                self.start_scan(drive)
        else:
            self.start_scan(self.folder_to_watch)

    def quick_scan(self):
        user_folder = os.path.expanduser("~")  # Get user's home directory
        self.start_scan(user_folder)

    def uefi_scan(self):
        folder_path = self.get_uefi_folder()
        self.start_scan(folder_path)

    def scan_folder(self):
        folder_path = QFileDialog.getExistingDirectory(None, "Select Folder to Scan")
        if folder_path:
            self.start_scan(folder_path)

    def scan_file(self):
        file_path, _ = QFileDialog.getOpenFileName(None, "Select File to Scan")
        if file_path:
            self.start_scan(file_path)

    def update_scan_labels(self):
        self.scanned_files_label.setText(f"Total Scanned Files: {self.total_scanned}")
        self.infected_files_label.setText(f"Infected Files: {self.infected_files}")
        self.clean_files_label.setText(f"Clean Files: {self.clean_files}")

    def pause_scanning(self):
        self.pause_event.clear()
        logging.info("Scanning paused")

    def resume_scanning(self):
        self.pause_event.set()
        logging.info("Scanning resumed")
        
    def stop_scanning(self):
        self.stop_event.set()
        logging.info("Scanning stopped")
        
    def reset_stop_event(self):
        self.stop_event.clear()
         
    def show_scan_finished_message(self):
        QMessageBox.information(self, "Scan Finished", "Folder scan has finished.")

    def show_memory_scan_finished_message(self):
        QMessageBox.information(self, "Scan Finished", "Memory scan has finished.")

    def apply_action(self):
        action = self.action_combobox.currentText()
        if action == "Quarantine All":
            self.quarantine_all_files()
        elif action == "Delete All":
            self.delete_all_files()
        elif action == "Skip All":
            self.skip_all_files()

    def handle_detected_files(self, quarantine=True):
        files_to_process = []
        for index in range(self.detected_list.count()):
            item = self.detected_list.item(index)
            file_path = item.data(Qt.UserRole)
            files_to_process.append(file_path)

        # Quarantine or delete all files simultaneously
        with ThreadPoolExecutor() as executor:
            if quarantine:
                executor.map(quarantine_file, files_to_process)
            else:
                executor.map(safe_remove, files_to_process)

        self.detected_list.clear()

    def quarantine_selected(self):
        selected_items = self.detected_list.selectedItems()
        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            virus_name = item.text().split("-")[-1].strip()
            quarantine_file(file_path, virus_name)

    def skip_selected(self):
        selected_items = self.detected_list.selectedItems()
        for item in selected_items:
            item_index = self.detected_list.row(item)
            self.detected_list.takeItem(item_index)

    def delete_selected(self):
        selected_items = self.detected_list.selectedItems()
        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            try:
                os.remove(file_path)
                self.detected_list.takeItem(self.detected_list.row(item))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete file: {str(e)}")

    def quarantine_all_files(self):
        self.handle_detected_files(quarantine=True)

    def delete_all_files(self):
        self.handle_detected_files(quarantine=False)

    def skip_all_files(self):
        self.detected_list.clear()

    def kill_all_malicious_processes(self):
        detected_threats = [self.detected_list.item(i) for i in range(self.detected_list.count())]
        malicious_processes = []

        for item in detected_threats:
            file_path = item.data(Qt.UserRole)
            try:
                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                    if proc.info['exe'] and os.path.abspath(proc.info['exe']) == os.path.abspath(file_path):
                        malicious_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                print(f"Error accessing process: {e}")

        for proc in malicious_processes:
            try:
                proc.kill()
                print(f"Killed process: {proc.info['pid']} ({proc.info['name']})")
            except psutil.NoSuchProcess:
                print(f"Process already killed: {proc.info['pid']} ({proc.info['name']})")
            except psutil.AccessDenied:
                print(f"Access denied when trying to kill process: {proc.info['pid']} ({proc.info['name']})")

    def scan_file_path(self, file_path):
        self.pause_event.wait()  # Wait if the scan is paused
        if self.stop_event.is_set():
            logging.info("Scan stopped.")
            return False, ""
        
        # Show the currently scanned file
        self.current_file_label.setText(f"Currently Scanning: {file_path}")
        logging.info(f"Scanning file: {file_path}")

        virus_name = ""

        if system_platform() in ['Windows', 'Linux', 'Darwin']:
            # Check for valid signature
            if preferences.get("check_valid_signature", False):
                if not self.valid_signature_exists(file_path):
                    logging.warning(f"Invalid signature detected: {file_path}")
                    virus_name = "Invalid Signature"
                else:
                    logging.info(f"Valid signature found for: {file_path}")
                    # Check for Microsoft signature only if the signature is valid
                    if preferences.get("check_microsoft_signature", False):
                        if self.hasMicrosoftSignature(file_path):
                            logging.info(f"File signed by Microsoft, skipping: {file_path}")
                            self.total_scanned += 1  # Increment total scanned count
                            self.clean_files += 1    # Increment clean files count
                            self.update_scan_labels()
                            return False, ""

            # Check with ClamAV if enabled and no issues found
            if not virus_name and preferences.get("use_clamav", False):
                virus_name = scan_file_with_clamd(file_path)
                if virus_name:
                    logging.warning(f"Virus detected by ClamAV in file: {file_path} - Virus: {virus_name}")

            # Check with YARA if enabled and no issues found
            if not virus_name and preferences.get("use_yara", False):
                yara_result = yara_scanner(file_path)
                if yara_result:
                    if isinstance(yara_result, list):
                        virus_name = ", ".join(yara_result)
                    else:
                        virus_name = yara_result
                    logging.warning(f"Virus detected by YARA in file: {file_path} - Virus: {virus_name}")

            # Check if the file is a zip archive and scan its content if it is
            if not virus_name and self.is_zip_file_classic(file_path):
                scan_result, virus_name = self.scan_zip_file_classic(file_path)
                if scan_result:
                    logging.warning(f"Infected file detected (ZIP): {file_path} - Virus: {virus_name}")
                else:
                    logging.info(f"No malware detected in ZIP file: {file_path}")
                    self.total_scanned += 1
                    self.clean_files += 1
                    self.update_scan_labels()
                    return False, ""

            # Check if the file is a PE file and scan it if it is
            if not virus_name and self.is_pe_file_classic(file_path):
                scan_result, virus_name = self.scan_pe_file_classic(file_path)
                if scan_result:
                    logging.warning(f"Infected file detected (PE): {file_path} - Virus: {virus_name}")
                else:
                    logging.info(f"No malware detected in PE file: {file_path}")
                    self.total_scanned += 1
                    self.clean_files += 1
                    self.update_scan_labels()
                    return False, ""

            # Check if the file is a tar archive and scan its content if it is
            if not virus_name and self.is_tar_file_classic(file_path):
                scan_result, virus_name = self.scan_tar_file_classic(file_path)
                if scan_result:
                    logging.warning(f"Infected file detected (TAR): {file_path} - Virus: {virus_name}")
                else:
                    logging.info(f"No malware detected in TAR file: {file_path}")
                    self.total_scanned += 1
                    self.clean_files += 1
                    self.update_scan_labels()
                    return False, ""

        # If malware is detected, add it to the detected list
        if virus_name:
            item = QListWidgetItem(f"Scanned file: {file_path} - Virus: {virus_name}")
            item.setData(Qt.UserRole, file_path)
            self.detected_list.addItem(item)
            self.total_scanned += 1
            self.infected_files += 1
            self.update_scan_labels()
            return True, virus_name

        # If no malware found, return False indicating the file is clean
        logging.info(f"File is clean: {file_path}")
        self.total_scanned += 1
        self.clean_files += 1
        self.update_scan_labels()
        return False, ""

class WorkerSignals(QObject):
    success = Signal()
    failure = Signal()

class AntivirusUI(QWidget):
    folder_scan_finished = Signal()
    # Define a new signal for memory scan finished
    memory_scan_finished = Signal()
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hydra Dragon Antivirus")
        self.stacked_widget = QStackedWidget()
        self.main_widget = QWidget()
        self.setup_main_ui()
        self.stacked_widget.addWidget(self.main_widget)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.stacked_widget)
        self.setLayout(main_layout)
        # Define pause_event and stop_event attributes
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.signals = WorkerSignals()
        self.signals.success.connect(self.show_success_message)
        self.signals.failure.connect(self.show_failure_message)

    def setup_main_ui(self):
        layout = QVBoxLayout()

        # Add the setup MBRFilter button only if on Windows
        if system_platform() == 'Windows':
            self.mbrfilter_button = QPushButton('Setup MBRFilter')
            self.mbrfilter_button.clicked.connect(setup_mbrfilter)
            layout.addWidget(self.mbrfilter_button)

        self.start_clamd_button = QPushButton("Start ClamAV")
        self.start_clamd_button.clicked.connect(start_clamd)
        layout.addWidget(self.start_clamd_button)

        self.load_website_signatures_button = QPushButton("Load Website Signatures")
        self.load_website_signatures_button.clicked.connect(self.load_website_signatures)
        layout.addWidget(self.load_website_signatures_button)
        
        self.preferences_button = QPushButton("Preferences")
        self.preferences_button.clicked.connect(self.show_preferences)
        layout.addWidget(self.preferences_button)

        self.scan_manager_button = QPushButton("Scan Manager")  # Add Scan Manager button
        self.scan_manager_button.clicked.connect(self.show_scan_manager)
        layout.addWidget(self.scan_manager_button)

        self.quarantine_button = QPushButton("Quarantine Manager")
        self.quarantine_button.clicked.connect(self.manage_quarantine)
        layout.addWidget(self.quarantine_button)

        self.update_definitions_button = QPushButton("Update Definitions")
        self.update_definitions_button.clicked.connect(self.update_definitions)
        layout.addWidget(self.update_definitions_button)

        self.setLayout(layout)

    def show_success_message(self):
        QMessageBox.information(self, "Update Definitions", "Antivirus definitions updated successfully.")

    def show_failure_message(self):
        QMessageBox.critical(self, "Update Definitions", "Failed to update antivirus definitions.")

    def load_website_signatures(self):
        load_data()  # Call the load_data function to load website signatures

    def show_scan_manager(self):
        scan_manager = ScanManager(self)
        scan_manager.show()

    def show_preferences(self):
        preferences_dialog = PreferencesDialog(self)
        if preferences_dialog.show() == QDialog.Accepted:
            global preferences
            preferences["use_machine_learning"] = preferences_dialog.use_machine_learning_checkbox.isChecked()
            preferences["use_clamav"] = preferences_dialog.use_clamav_checkbox.isChecked()
            preferences["use_yara"] = preferences_dialog.use_yara_checkbox.isChecked()
            preferences["real_time_protection"] = preferences_dialog.real_time_protection_checkbox.isChecked()
            preferences["real_time_web_protection"] = preferences_dialog.real_time_web_protection_checkbox.isChecked()
            preferences["enable_hips"] = preferences_dialog.enable_hips_checkbox.isChecked()
            save_preferences(preferences)

    def manage_quarantine(self):
        quarantine_manager = QuarantineManager(self)
        quarantine_manager.show()

    def update_definitions(self):
        def run_update():
            result = subprocess.run(["freshclam"], capture_output=True)
            if result.returncode == 0:
                self.signals.success.emit()
            else:
                self.signals.failure.emit()

        update_thread = threading.Thread(target=run_update)
        update_thread.start()

class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        layout = QVBoxLayout()

        self.use_clamav_checkbox = QCheckBox("Use ClamAV Engine")
        self.use_clamav_checkbox.setChecked(preferences["use_clamav"])
        layout.addWidget(self.use_clamav_checkbox)

        self.use_yara_checkbox = QCheckBox("Use YARA Engine")
        self.use_yara_checkbox.setChecked(preferences["use_yara"])
        layout.addWidget(self.use_yara_checkbox)

        self.use_machine_learning_checkbox = QCheckBox("Use Machine Learning AI Engine")
        self.use_machine_learning_checkbox.setChecked(preferences["use_machine_learning"])
        layout.addWidget(self.use_machine_learning_checkbox)
        
        self.real_time_protection_checkbox = QCheckBox("Limited Real-Time Protection")
        self.real_time_protection_checkbox.setChecked(preferences["real_time_protection"])
        self.real_time_protection_checkbox.stateChanged.connect(self.toggle_real_time_protection)
        layout.addWidget(self.real_time_protection_checkbox)

        self.real_time_web_protection_checkbox = QCheckBox("Limited Real-Time Web Protection")
        self.real_time_web_protection_checkbox.setChecked(preferences["real_time_web_protection"])
        self.real_time_web_protection_checkbox.stateChanged.connect(self.toggle_real_time_web_protection)
        layout.addWidget(self.real_time_web_protection_checkbox)
        
        self.enable_hips_checkbox = QCheckBox("Enable Snort HIPS")
        self.enable_hips_checkbox.setChecked(preferences["enable_hips"])
        self.enable_hips_checkbox.stateChanged.connect(self.toggle_hips)
        layout.addWidget(self.enable_hips_checkbox)

        if system_platform() in ['Windows', 'Linux', 'Darwin']:
            self.valid_signature_checkbox = QCheckBox("Check valid signature (Improve Detection)")
            self.valid_signature_checkbox.setChecked(preferences.get("check_valid_signature", False))
            layout.addWidget(self.valid_signature_checkbox)

            self.microsoft_signature_checkbox = QCheckBox("Check Microsoft signature (Less F/P And Optimization)")
            self.microsoft_signature_checkbox.setChecked(preferences.get("check_microsoft_signature", False))
            layout.addWidget(self.microsoft_signature_checkbox)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def toggle_real_time_protection(self, state):
        preferences["real_time_protection"] = (state == Qt.Checked)
        save_preferences(preferences)
        if state == Qt.Checked:
            self.start_real_time_protection()
        else:
            self.stop_real_time_protection()

    def toggle_real_time_web_protection(self, state):
        preferences["real_time_web_protection"] = (state == Qt.Checked)
        save_preferences(preferences)
        if state == Qt.Checked:
            self.start_real_time_web_protection()
        else:
            self.stop_real_time_web_protection()

    def toggle_hips(self, state):
        preferences["enable_hips"] = (state == Qt.Checked)
        save_preferences(preferences)
        if state == Qt.Checked:
            self.start_hips()
        else:
            self.stop_hips()

    def start_real_time_protection(self):
        global real_time_observer
        real_time_observer.start()

    def stop_real_time_protection(self):
        global real_time_observer
        if real_time_observer and real_time_observer.is_started:
            real_time_observer.stop()

    def start_real_time_web_protection(self):
        global real_time_web_observer
        real_time_web_observer.start()

    def stop_real_time_web_protection(self):
        global real_time_web_observer
        if real_time_web_observer and real_time_web_observer.is_started:
            real_time_web_observer.stop()

    def start_hips(self):
        global snort_observer
        snort_observer.start()

    def stop_hips(self):
        global snort_observer
        if snort_observer and snort_observer.is_started:
            snort_observer.stop()
            print("Snort is now disabled.")

    def accept(self):
        preferences["use_clamav"] = self.use_clamav_checkbox.isChecked()
        preferences["use_yara"] = self.use_yara_checkbox.isChecked()
        preferences["use_machine_learning"] = self.use_machine_learning_checkbox.isChecked()
        preferences["real_time_protection"] = self.real_time_protection_checkbox.isChecked()
        preferences["real_time_web_protection"] = self.real_time_web_protection_checkbox.isChecked()
        preferences["enable_hips"] = self.enable_hips_checkbox.isChecked()
        
        if system_platform() in ['Windows', 'Linux', 'Darwin']:
            preferences["check_valid_signature"] = self.valid_signature_checkbox.isChecked()
            preferences["check_microsoft_signature"] = self.microsoft_signature_checkbox.isChecked()

        save_preferences(preferences)
        super().accept()

class QuarantineManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quarantine Manager")
        layout = QVBoxLayout()

        self.quarantine_list = QListWidget()
        for entry in quarantine_data:
            item = QListWidgetItem(f"{entry['original_path']} - Virus: {entry['virus_name']}")
            item.setData(Qt.UserRole, entry['original_path'])
            self.quarantine_list.addItem(item)
        layout.addWidget(self.quarantine_list)

        self.action_button_layout = QHBoxLayout()

        self.restore_button = QPushButton("Restore Selected")
        self.restore_button.clicked.connect(self.restore_selected)
        self.action_button_layout.addWidget(self.restore_button)

        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.clicked.connect(self.delete_selected)
        self.action_button_layout.addWidget(self.delete_button)

        self.restore_all_button = QPushButton("Restore All")
        self.restore_all_button.clicked.connect(self.restore_all)
        self.action_button_layout.addWidget(self.restore_all_button)

        self.delete_all_button = QPushButton("Delete All")
        self.delete_all_button.clicked.connect(self.delete_all_files_quar)
        self.action_button_layout.addWidget(self.delete_all_button)

        layout.addLayout(self.action_button_layout)

        self.setLayout(layout)

    def delete_all_files_quar(self):
        save_quarantine_data(quarantine_data)
        self.quarantine_list.clear()

    def restore_selected(self):
        selected_items = self.quarantine_list.selectedItems()
        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            try:
                # Find the entry in quarantine_data corresponding to the selected file
                selected_entry = next(entry for entry in quarantine_data if entry['quarantine_path'] == file_path)
                original_path = selected_entry['original_path']
                # Restore the file to its original location
                shutil.move(file_path, original_path)
                # Remove the item from the list widget
                self.quarantine_list.takeItem(self.quarantine_list.row(item))
                # Remove the entry from quarantine_data
                quarantine_data.remove(selected_entry)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to restore file: {str(e)}")
        # Save the updated quarantine data
        save_quarantine_data(quarantine_data)

    def delete_selected(self):
        selected_items = self.quarantine_list.selectedItems()
        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            try:
                os.remove(file_path)
                self.quarantine_list.takeItem(self.quarantine_list.row(item))
                quarantine_data = [entry for entry in quarantine_data if entry['file_path'] != file_path]
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete file: {str(e)}")
        save_quarantine_data(quarantine_data)

    def restore_all(self):
        for entry in quarantine_data:
            file_path = entry['file_path']
            try:
                shutil.move(file_path, os.path.join(os.getcwd(), os.path.basename(file_path)))
                self.quarantine_list.clear()
                quarantine_data = []
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to restore file: {str(e)}")
        save_quarantine_data(quarantine_data)
        
if __name__ == "__main__":
    try:
        # Create a thread for monitoring preferences
        preferences_thread = threading.Thread(target=monitor_preferences)
        preferences_thread.daemon = True  # Daemonize the thread so it exits when the main thread exits
        preferences_thread.start()
        # Create a thread for monitoring preferences
        web_preferences_thread = threading.Thread(target=monitor_web_preferences)
        web_preferences_thread.daemon = True  # Daemonize the thread so it exits when the main thread exits
        web_preferences_thread.start()
        # Create a thread for monitoring preferences
        snort_preferences_thread = threading.Thread(target=monitor_snort_preferences)
        snort_preferences_thread.daemon = True  # Daemonize the thread so it exits when the main thread exits
        snort_preferences_thread.start()
        app = QApplication(sys.argv)
        main_gui = AntivirusUI()
        # Initialize the ScanManager
        scan_manager = ScanManager()
         # Connect signals to the ScanManager's slots
        scan_manager.folder_scan_finished.connect(scan_manager.folder_scan_finished.emit)
        scan_manager.memory_scan_finished.connect(scan_manager.memory_scan_finished.emit)
        main_gui.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"An error occurred: {e}")