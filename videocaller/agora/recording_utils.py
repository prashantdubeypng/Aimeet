"""
Agora Cloud Recording utilities for managing recording lifecycle and S3 uploads
"""
import os
import time
import base64
import requests
import boto3
from django.conf import settings
from botocore.exceptions import ClientError


class AgoraCloudRecording:
    """Handles Agora Cloud Recording API operations"""
    
    def __init__(self):
        self.app_id = settings.AGORA_APP_ID
        self.customer_id = settings.AGORA_CUSTOMER_ID
        self.customer_secret = settings.AGORA_CUSTOMER_SECRET
        self.region = settings.AGORA_RECORDING_REGION
        
        # Base URL for Agora Cloud Recording API
        region_map = {
            'NA': 'https://api.agora.io/v1/apps',
            'EU': 'https://api-eu.agora.io/v1/apps',
            'AP': 'https://api-ap.agora.io/v1/apps',
            'CN': 'https://api-cn.agora.io/v1/apps'
        }
        self.base_url = region_map.get(self.region, region_map['NA'])
        
    def _get_auth_header(self):
        """Generate Basic Auth header for Agora API"""
        credentials = f"{self.customer_id}:{self.customer_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {encoded}', 'Content-Type': 'application/json'}
    
    def acquire_resource(self, channel_name, uid):
        """
        Acquire a resource ID for cloud recording
        
        Args:
            channel_name: The channel to record
            uid: The UID for the recording bot (should be unique and not used by any user)
            
        Returns:
            dict: {'resourceId': 'xxx', 'success': True/False}
        """
        url = f"{self.base_url}/{self.app_id}/cloud_recording/acquire"
        
        payload = {
            "cname": channel_name,
            "uid": str(uid),
            "clientRequest": {
                "resourceExpiredHour": 24,
                "scene": 0  # 0 for real-time recording
            }
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_auth_header())
            response.raise_for_status()
            data = response.json()
            return {
                'resourceId': data.get('resourceId'),
                'success': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def start_recording(self, channel_name, uid, resource_id, token, bucket_name, bucket_access_key, 
                       bucket_secret_key, bucket_region):
        """
        Start cloud recording
        
        Args:
            channel_name: Channel to record
            uid: Recording bot UID
            resource_id: Resource ID from acquire
            token: Agora RTC token for the recording bot
            bucket_name: S3 bucket name
            bucket_access_key: AWS access key
            bucket_secret_key: AWS secret key
            bucket_region: AWS region (0=us-east-1, 1=us-east-2, etc.)
            
        Returns:
            dict: {'sid': 'xxx', 'resourceId': 'xxx', 'success': True/False}
        """
        url = f"{self.base_url}/{self.app_id}/cloud_recording/resourceid/{resource_id}/mode/mix/start"
        
        # Region mapping for S3
        region_code_map = {
            'us-east-1': 0, 'us-east-2': 1, 'us-west-1': 2, 'us-west-2': 3,
            'eu-west-1': 4, 'eu-west-2': 5, 'eu-west-3': 6, 'eu-central-1': 7,
            'ap-southeast-1': 8, 'ap-southeast-2': 9, 'ap-northeast-1': 10,
            'ap-northeast-2': 11, 'sa-east-1': 12, 'ca-central-1': 13,
            'ap-south-1': 14, 'cn-north-1': 15, 'cn-northwest-1': 16
        }
        
        payload = {
            "cname": channel_name,
            "uid": str(uid),
            "clientRequest": {
                "token": token,
                "recordingConfig": {
                    "maxIdleTime": 30,
                    "streamTypes": 2,  # 0=audio, 1=video, 2=both
                    "channelType": 0,  # 0=communication, 1=live broadcast
                    "videoStreamType": 0,  # 0=high stream, 1=low stream
                    "subscribeUidGroup": 0  # Record all users
                },
                "recordingFileConfig": {
                    "avFileType": ["hls", "mp4"]  # HLS for live, MP4 for download
                },
                "storageConfig": {
                    "vendor": 1,  # 1=AWS S3, 2=Alibaba Cloud, 3=Tencent Cloud
                    "region": region_code_map.get(bucket_region, 0),
                    "bucket": bucket_name,
                    "accessKey": bucket_access_key,
                    "secretKey": bucket_secret_key,
                    "fileNamePrefix": [f"recordings/{channel_name}"]
                }
            }
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_auth_header())
            response.raise_for_status()
            data = response.json()
            return {
                'sid': data.get('sid'),
                'resourceId': data.get('resourceId'),
                'success': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e),
                'response': response.text if 'response' in locals() else None
            }
    
    def stop_recording(self, channel_name, uid, resource_id, sid):
        """
        Stop cloud recording
        
        Args:
            channel_name: Channel being recorded
            uid: Recording bot UID
            resource_id: Resource ID from acquire
            sid: Session ID from start
            
        Returns:
            dict: {'serverResponse': {...}, 'success': True/False}
        """
        url = f"{self.base_url}/{self.app_id}/cloud_recording/resourceid/{resource_id}/sid/{sid}/mode/mix/stop"
        
        payload = {
            "cname": channel_name,
            "uid": str(uid),
            "clientRequest": {}
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_auth_header())
            response.raise_for_status()
            data = response.json()
            return {
                'serverResponse': data.get('serverResponse', {}),
                'success': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def query_recording(self, resource_id, sid):
        """
        Query recording status
        
        Args:
            resource_id: Resource ID from acquire
            sid: Session ID from start
            
        Returns:
            dict: {'serverResponse': {...}, 'success': True/False}
        """
        url = f"{self.base_url}/{self.app_id}/cloud_recording/resourceid/{resource_id}/sid/{sid}/mode/mix/query"
        
        try:
            response = requests.get(url, headers=self._get_auth_header())
            response.raise_for_status()
            data = response.json()
            return {
                'serverResponse': data.get('serverResponse', {}),
                'success': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }


class S3Manager:
    """Handles AWS S3 operations for recordings"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        self.bucket_name = settings.AWS_STORAGE_BUCKET_NAME
    
    def generate_presigned_url(self, s3_key, expiration=3600):
        """
        Generate a presigned URL for accessing S3 object
        
        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default 1 hour)
            
        Returns:
            str: Presigned URL or None if error
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            return None
    
    def upload_file(self, file_path, s3_key):
        """
        Upload a file to S3
        
        Args:
            file_path: Local file path
            s3_key: S3 object key
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.s3_client.upload_file(file_path, self.bucket_name, s3_key)
            return True
        except ClientError as e:
            print(f"Error uploading to S3: {e}")
            return False
    
    def get_s3_url(self, s3_key):
        """
        Get public S3 URL (for public buckets) or object location
        
        Args:
            s3_key: S3 object key
            
        Returns:
            str: S3 URL
        """
        return f"https://{self.bucket_name}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{s3_key}"
    
    def check_file_exists(self, s3_key):
        """
        Check if a file exists in S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            bool: True if exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError:
            return False
