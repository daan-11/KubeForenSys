from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient
from azure.core.exceptions import HttpResponseError

import math
import logging

class AzureConnector:
    def __init__(self, endpoint_uri):
        self.setup_envs(endpoint_uri=endpoint_uri)
        self.authenticate()
        self.BATCH_SIZE = 500
        self.logger = logging.getLogger("appLogger")
    
    def setup_envs(self, endpoint_uri):
        self.endpoint_uri = endpoint_uri
        if not self.endpoint_uri:
            raise EnvironmentError(f"Required values not set: endpoint_uri: {self.endpoint_uri}")

    def authenticate(self):
        credential = DefaultAzureCredential()
        self.client = LogsIngestionClient(endpoint=self.endpoint_uri, credential=credential, logging_enabled=True)

    def upload_in_batches(self, generator_function, stream_name, dcr_stream_id):
        batch = []
        counter = 0

        self.logger.info(f"Uploading to {stream_name}")
        try:
            for entry in generator_function():
                batch.append(entry)
                if len(batch) >= self.BATCH_SIZE:
                    print(f"Uploading batch of size {len(batch)} to {dcr_stream_id} - \n {batch}")
                    try:
                        self.client.upload(
                            rule_id=dcr_stream_id,
                            stream_name=stream_name,
                            logs=batch
                        )
                        counter += len(batch)
                    except Exception as e:
                        self.logger.error(f"Exception during upload of batch to {stream_name}: {e}")
                    batch.clear()

            # upload last batch which does not exceed batch size
            if batch:
                try:
                    self.client.upload(
                        rule_id=dcr_stream_id,
                        stream_name=stream_name,
                        logs=batch
                    )
                    counter += len(batch)
                except Exception as e:
                    self.logger.error(f"Exception during upload of final batch to {stream_name}: {e}")
        except Exception as e:
            self.logger.error(f"Exception in upload_in_batches for {stream_name}: {e}")
        self.logger.info(f"Total entries uploaded: {counter} to {stream_name}")