#!/usr/bin/env python3
import sys
import subprocess
from azure.storage.blob import BlockBlobService

from selfdrive.test.test_car_models import routes as test_car_models_routes
from selfdrive.test.process_replay.test_processes import segments as replay_segments
from xx.chffr.lib import azureutil  # pylint: disable=import-error
from xx.chffr.lib.storage import _DATA_ACCOUNT_PRODUCTION, _DATA_ACCOUNT_CI, _DATA_BUCKET_PRODUCTION  # pylint: disable=import-error

SOURCES = [
  (_DATA_ACCOUNT_PRODUCTION, _DATA_BUCKET_PRODUCTION),
  (_DATA_ACCOUNT_PRODUCTION, "preserve"),
  (_DATA_ACCOUNT_CI, "commadataci"),
]

DEST_KEY = azureutil.get_user_token(_DATA_ACCOUNT_CI, "openpilotci")
SOURCE_KEYS = [azureutil.get_user_token(account, bucket) for account, bucket in SOURCES]
SERVICE = BlockBlobService(_DATA_ACCOUNT_CI, sas_token=DEST_KEY)

def sync_to_ci_public(route):
  print(f"Uploading {route}")
  key_prefix = route.replace('|', '/')
  dongle_id = key_prefix.split('/')[0]

  if next(azureutil.list_all_blobs(SERVICE, "openpilotci", prefix=key_prefix), None) is not None:
    print("Already synced")
    return True

  for (source_account, source_bucket), source_key in zip(SOURCES, SOURCE_KEYS):
    print(f"Trying {source_account}/{source_bucket}")
    cmd = [
      "azcopy",
      "copy",
      "https://{}.blob.core.windows.net/{}/{}?{}".format(source_account, source_bucket, key_prefix, source_key),
      "https://{}.blob.core.windows.net/{}/{}?{}".format(_DATA_ACCOUNT_CI, "openpilotci", dongle_id, DEST_KEY),
      "--recursive=true",
      "--overwrite=false",
      "--exclude-pattern=*/dcamera.hevc",
    ]

    try:
      result = subprocess.call(cmd, stdout=subprocess.DEVNULL)
      if result == 0:
        print("Success")
        return True
    except subprocess.CalledProcessError:
      print("Failed")

  return False


if __name__ == "__main__":
  failed_routes = []

  to_sync = sys.argv[1:]

  if not len(to_sync):
    # sync routes from test_car_models and process replay
    to_sync.extend(test_car_models_routes.keys())
    to_sync.extend([s[1].rsplit('--', 1)[0] for s in replay_segments])

  for r in to_sync:
    if not sync_to_ci_public(r):
      failed_routes.append(r)

  if len(failed_routes):
    print("failed routes:", failed_routes)
