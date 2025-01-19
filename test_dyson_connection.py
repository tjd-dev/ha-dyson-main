import asyncio
import logging
from datetime import datetime
import json
import ssl
import certifi
import socket

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

# Your device credentials
SERIAL = "H5R-US-TDA2255A"
CREDENTIAL = "d3DpQ4B1M30ZAWqz3ZcJ4qSVe3TwISxwn88O4362ACLS0NIfQwO1VeWMbmDWcRQOVbIHhgBAryFtZhlazegROw=="
DEVICE_TYPE = "277"  # Vis Nav product type

# IoT credentials
IOT_HOST = "a1u2wvl3e2lrc4-ats.iot.eu-west-1.amazonaws.com"
CLIENT_ID = "6e98b16d-751e-4c62-bce3-986498e88a05"
TOKEN_VALUE = "6e98b16d-751e-4c62-bce3-986498e88a05"
TOKEN_SIGNATURE = "F3TVdUz0JjPQuTH2eShYcvII6d7xmND9myhS0/fyhcsC4XuO+vXOn/pVNMPjSo2YyHtPx5ys3/lfNXWsNOAKd2VP+s15RNFL+mAQrOYjkWImqObWz1bJDsr4yq/yrctO+pZ4AO1DGfxXy7EtCcCKUID1ku2FiQkYXb+FDfGfVk4VOeuqtT/iLZYNAO60ZYvWp1Y/4oGt7uDAqEVjKulze9lzRJzdNxFOp6Eqre0asUcRuEfsGjyHIKJnMFzmVW6lYEF+S9/f4SvMhYDNvh+1Og36KpS/Yif4JQG0ElugnJPSsDUIC8yd8Ved2DcUOSQ8wMJCNTBLUDu37n15azW/Og=="

import paho.mqtt.client as mqtt

class DysonTest:
    def __init__(self):
        self.mqtt_client = None
        self.connected = False
        self.last_message = None
        self.message_received = asyncio.Event()

    def on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT client connects."""
        _LOGGER.info("MQTT Connected with result code: %s", rc)
        if rc == 0:
            self.connected = True
            # Subscribe to all topics for this device
            topic = f"{DEVICE_TYPE}/{SERIAL}/#"
            client.subscribe(topic)
            _LOGGER.info("Subscribed to topic: %s", topic)
        else:
            _LOGGER.error("Failed to connect. Result code: %s", rc)

    def on_disconnect(self, client, userdata, rc):
        """Callback when client disconnects."""
        _LOGGER.info("Disconnected with result code: %s", rc)
        self.connected = False

    def on_message(self, client, userdata, msg):
        """Callback when MQTT message is received."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            _LOGGER.info("Topic: %s", msg.topic)
            _LOGGER.info("Payload: %s", json.dumps(payload, indent=2))
            self.last_message = {
                'topic': msg.topic,
                'payload': payload,
                'timestamp': datetime.now().isoformat()
            }
            self.message_received.set()
        except Exception as e:
            _LOGGER.error("Error processing message: %s", e)

    def on_log(self, client, userdata, level, buf):
        """Callback for MQTT client logging."""
        _LOGGER.debug("MQTT Log: %s", buf)

    def connect(self):
        """Connect to MQTT broker."""
        try:
            # Create new MQTT client
            self.mqtt_client = mqtt.Client(
                client_id=CLIENT_ID,
                protocol=mqtt.MQTTv311,  # Using v3.1.1
                transport="tcp"
            )
            
            # Set callbacks
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect
            self.mqtt_client.on_log = self.on_log

            # Enable debugging
            self.mqtt_client.enable_logger()

            # Configure TLS
            ssl_context = ssl.create_default_context(
                cafile=certifi.where()
            )
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            ssl_context.check_hostname = True
            
            # Set minimum TLS version to 1.2
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            
            self.mqtt_client.tls_set_context(ssl_context)
            
            # Set credentials
            self.mqtt_client.username_pw_set(
                username=CLIENT_ID,
                password=TOKEN_VALUE
            )

            # Set socket options
            self.mqtt_client.socket_options = (
                (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
            )

            _LOGGER.info("Connecting to %s:8883", IOT_HOST)
            
            # Connect with standard parameters for v3.1.1
            self.mqtt_client.connect(
                IOT_HOST,
                port=8883,
                keepalive=60
            )
            
            self.mqtt_client.loop_start()
            return True

        except Exception as e:
            _LOGGER.error("Connection failed: %s", e, exc_info=True)
            return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                _LOGGER.error("Error during disconnect: %s", e)

async def main():
    dyson = DysonTest()
    
    if dyson.connect():
        try:
            # Wait for up to 30 seconds for a message
            _LOGGER.info("Waiting for messages...")
            try:
                await asyncio.wait_for(dyson.message_received.wait(), timeout=30.0)
                _LOGGER.info("Connection test successful!")
                if dyson.last_message:
                    _LOGGER.info("Last message received:")
                    _LOGGER.info("Topic: %s", dyson.last_message['topic'])
                    _LOGGER.info("Payload: %s", json.dumps(dyson.last_message['payload'], indent=2))
                    _LOGGER.info("Time: %s", dyson.last_message['timestamp'])
            except asyncio.TimeoutError:
                _LOGGER.error("No messages received within timeout period")
        finally:
            dyson.disconnect()
    else:
        _LOGGER.error("Failed to start connection")

if __name__ == "__main__":
    asyncio.run(main()) 