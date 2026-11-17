# FASTCON BLE Gateway UDP Open Interface Specification

**Version:** 0.8  
**Date:** 2023-09-15  

---

## Revision History

| No. | Version | Change Description | Date | Contributors |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 0.1 | Initial version. | | |
| 2 | 0.2 | Added device list retrieval and control workflow. | | |
| 3 | 0.3 | 1. Retained only mode and port parameter configurations.<br>2. Added "Device Info URL" generation feature, along with request and response message definitions.<br>3. Revised descriptions for device control requests and responses.<br>4. Detailed data reporting commands and data formats. | | |
| 4 | 0.5 | Simplified workflow processes. | | |
| 5 | 0.6 | Added local LAN sharing of family/home data. | | |
| 6 | 0.7 | 1. Added temporary group configuration.<br>2. Added status querying and parsing for devices with short addresses greater than 255. | 2023-05-12 | |
| 7 | 0.8 | Added UART serial commands 46 through 51. | 2023-09-14 | |

---

## 1. Introduction

### 1.1 Purpose
As a node in network communications, a gateway functions to process or forward network packets. Gateways integrated with Bluetooth modules or Bluetooth SoC chips possess the capability to control Bluetooth devices and gather device telemetry. 

Consequently, the gateway can forward collected data to cloud platforms for further processing and pass downstream control commands (either by transparent passthrough or after protocol conversion) to end devices via the Bluetooth protocol. The host platform may be an on-premises local server or a public cloud server, communicating with the gateway through standardized protocols. Control instructions can be generated on the host system, transmitted across the network tunnel to the gateway, and subsequently processed and dispatched to the Bluetooth sub-devices.

This document defines how the gateway establishes connections with host controllers/servers when operating in either **Server Mode** (listening on an open port) or **Client Mode** (actively connecting to an external service), and specifies the underlying protocol packet formats.

### 1.2 Terminology

| Term | Description |
| :--- | :--- |
| **Controller / Client (`控制端`)** | A third-party device or system that controls Bluetooth devices via the gateway. |
| **Private Data (`私有数据`)** | Proprietary BroadLink configuration data that can be customized, stored, and queried. |

### 1.3 Reference Documents

| No. | Document Title | Description |
| :--- | :--- | :--- |
| 1 | *UART Communication Protocol for Transparent BLE Modules* | Hardware serial specification. |

---

## 2. System Overview

### Overall Workflow
1. **Device Provisioning:** The gateway and Bluetooth sub-devices are paired and added via the "e-Control Home" ("易控全屋") App. Device metadata is automatically synchronized to the BroadLink Cloud.
2. **Parameter Configuration:** The App or Cloud platform configures the gateway's private data parameters, defining its operational mode (Server or Client) and networking parameters (port, IP/address).
   - **Server Mode:** The gateway opens a designated UDP port and listens for client connections.
   - **Client Mode:** The gateway initiates a UDP connection to a designated host and port.
3. **Configuration Notification:** The cloud platform notifies the gateway of parameter updates. The gateway stores the configuration and switches its operational mode accordingly.
4. **Device Metadata Retrieval:** The gateway maintains only essential operational parameters (cluster domain, auth tokens, etc.). Full device manifests, scene definitions, and room configurations are stored in the cloud. Before issuing device commands, the controller must request a "Device Information URL" from the gateway:
   - The controller sends a request for the configuration URL to the gateway.
   - The gateway generates a temporary signed URL and returns it to the controller.
   - The controller executes an HTTP/HTTPS GET request against this URL, parses the payload, and caches all relevant device data locally.
5. **Device Control:** The controller constructs and transmits control payloads to the gateway based on specific device categories and endpoints.

---

### 2.1 Server Mode Workflow

```
Cloud Server                 Gateway (Server Mode)             Controller (Client Mode)
     |                                |                                   |
     |--- Notify Private Data Update->|                                   |
     |                                | [Cache parameters & apply mode]   |
     |                                |                                   |
     |                                |<--- Probe Request (Broadcast) ----|
     |                                |---- Probe Response (Unicast) ---->|
     |                                |                                   |
     |                                |<--- Heartbeat Request (15s) ------|
     |                                |---- Heartbeat Response ---------->|
     |                                |                                   |
```

1. The gateway retrieves configuration parameters from the cloud, activates Server Mode, opens the designated UDP listening port, and waits for incoming client packets.
2. **Connection Establishment:**
   - **Discovery:** The client transmits a LAN **Probe Request** (broadcast). The gateway responds with a unicast **Probe Response**. *(Note: If the client already knows the gateway's IP address and port, discovery can be bypassed directly in favor of the Heartbeat exchange).*
   - **Binding / Session Registration:** The client sends an initial binding/heartbeat packet to the gateway.
3. **Session Keep-Alive:**
   - Once connected, the client **must send a Heartbeat Request every 15 seconds**. The gateway immediately responds with a Heartbeat Response.
   - **Gateway Timeout Policy:** If 5 consecutive heartbeat packets are missed from a registered client (~75 seconds), the gateway drops the client from its active session table.
   - **Client Timeout Policy:** If 5 consecutive heartbeat responses are missed from the gateway, the client must trigger the discovery/re-binding sequence again.
   - **Capacity:** The gateway supports up to **16 concurrent client connections** (subject to hardware resource constraints).

---

### 2.2 Client Mode Workflow

```
Cloud Server                 Gateway (Client Mode)             Controller (Server Mode)
     |                                |                                   |
     |--- Notify Private Data Update->|                                   |
     |                                | [Cache parameters & apply mode]   |
     |                                |                                   |
     |                                |---- Bind / Heartbeat Request ---->|
     |                                |<--- Bind / Heartbeat Response ----|
     |                                |                                   |
     |                                |---- Heartbeat Request (15s) ----->|
     |                                |<--- Heartbeat Response -----------|
     |                                |                                   |
```

1. The gateway receives configuration parameters from the cloud and sets its operating mode to Client Mode.
2. **Connection Establishment:**
   - If the target server address is configured as a domain name, the gateway performs a DNS lookup to resolve the IP address.
   - The gateway initiates communication by sending a packet to the remote controller's open port.
3. **Session Keep-Alive:**
   - The gateway sends a **Heartbeat Request every 15 seconds** to the controller server. The controller server must reply with a Heartbeat Response immediately.
   - **Server Timeout Policy:** If 5 consecutive heartbeats are missed from the gateway, the server purges the gateway session.
   - **Gateway Timeout Policy:** If 5 consecutive heartbeat responses are missed, the gateway re-initiates the connection and DNS lookup process.
   - **Constraint:** In Client Mode, the gateway can connect to only **one** remote server.

---

### 2.3 Parameter Settings

The networking configuration is stored in the gateway's private data storage under the tag:
- **`mtag`**: `udp_service`
- **`data`** (JSON format):
```json
{
  "mode": 1,
  "port": 54321,
  "address": "172.168.1.199"
}
```

#### Parameter Field Definitions

| Field | Type | Values | Description |
| :--- | :--- | :--- | :--- |
| `mode` | ENUM | `0`, `1`, `2` | Gateway operating mode:<br>• `0`: Default mode (Networking disabled; does not connect and cannot be connected).<br>• `1`: Server Mode (Opens local port and listens for external clients).<br>• `2`: Client Mode (Gateway connects to an external server port). |
| `port` | Integer | Valid Port | UDP port number:<br>• In **Server Mode**, the gateway opens this port for inbound UDP traffic.<br>• In **Client Mode**, this specifies the target port on the remote controller server. |
| `address` | String | IP / FQDN | Host address (dotted-decimal IPv4 or FQDN):<br>• In **Server Mode**, this field is optional/unused.<br>• In **Client Mode**, this specifies the remote controller IP/domain. |

---

### 2.4 Data Communication Protocol

A complete UDP frame consists of a **Protocol Header** followed by a **Data Payload**.

#### UART Serial Framing (When using UART instead of direct UDP)
If communication occurs over a hardware UART serial interface (Baud rate: **9600 bps**), frames must include a 4-byte UART framing prefix:

| Magic (1 Byte) | Checksum (1 Byte) | Length (1 Byte) | Reserved (1 Byte) | Payload |
| :---: | :---: | :---: | :---: | :---: |
| `0x5A` | Frame Checksum | Total Frame Length | `0x00` | Protocol Header + Data Payload |

The UART checksum represents the 8-bit cumulative sum of all frame bytes:
```c
uint8_t calc_crc(uint8_t* buf, uint8_t len)
{
    uint8_t i = 0;
    uint8_t crc_cal = 0;
    for (i = 0; i < len; i++) {
        crc_cal += buf[i];
    }
    return crc_cal;
}
```

---

#### Protocol Header Structure

```c
typedef struct __attribute__((packed)) {
    uint16_t type;  /* Message Type (Little-Endian) */
    uint16_t seq;   /* Sequence Number (Little-Endian) */
} message_head_t;
```

- **`type`**: 16-bit unsigned integer in **Little-Endian** format representing the command/message ID.
- **`seq`**: 16-bit sequence counter in **Little-Endian** format. Maintained by the sender (incremented by 1 per request). The recipient must mirror this value in its corresponding response. Senders use this field to pair requests with responses and filter out duplicates.
- **Byte Order Rule:** Unless explicitly noted otherwise, `type` and `seq` are **Little-Endian**; other multi-byte payload fields default to **Big-Endian**.

---

#### Message Type Reference Table

| Type ID | Message Name | Direction / Transport | Description |
| :---: | :--- | :--- | :--- |
| **1** | Probe Request | Client $\to$ Gateway (UDP) | Gateway discovery request. |
| **2** | Probe Response | Gateway $\to$ Client (UDP) | Gateway discovery response. |
| **3** | Heartbeat Request | Client $\leftrightarrow$ Gateway | Keep-alive ping (sent every 15s). |
| **4** | Heartbeat Response | Client $\leftrightarrow$ Gateway | Keep-alive response. |
| **5** | Device Info URL Request | Client $\to$ Gateway | Request URL to download device manifest. |
| **6** | Device Info URL Response | Gateway $\to$ Client | Returns temporary download URL. |
| **9** | Short Address Control Request | Client $\to$ Gateway | Unicast control command to a sub-device. |
| **10** | Short Address Control Response| Gateway $\to$ Client | Acknowledgement of short address control. |
| **11** | Scene Control Request | Client $\to$ Gateway | Trigger a scene execution. |
| **12** | Scene Control Response | Gateway $\to$ Client | Acknowledgement of scene execution. |
| **13** | Group Control Request | Client $\to$ Gateway | Multicast control to a device group. |
| **14** | Group Control Response | Gateway $\to$ Client | Acknowledgement of group control. |
| **15** | Data Report Request | Gateway $\to$ Client | Telemetry/state report from sub-devices. |
| **16** | Data Report Response | Client $\to$ Gateway | Acknowledgement of telemetry report. |
| **17** | Trigger Device Status Report | Client $\to$ Gateway | Queries device(s) for immediate status report. |
| **18** | Trigger Status Report Response| Gateway $\to$ Client | Acknowledgement of trigger command. |
| **19** | Set Temporary Group Request | Client $\to$ Gateway | Configures an ephemeral broadcast group. |
| **20** | Set Temporary Group Response | Gateway $\to$ Client | Acknowledgement of temporary group setup. |
| **21** | Color Mode by Short Addr Req | Client $\to$ Gateway | Set lighting color mode via short address. |
| **22** | Color Mode by Short Addr Resp| Gateway $\to$ Client | Acknowledgement. |
| **23** | Color Mode by Group Req | Client $\to$ Gateway | Set lighting color mode via group ID. |
| **24** | Color Mode by Group Resp | Gateway $\to$ Client | Acknowledgement. |
| **25** | Sleep/Wake Mode by Short Addr | Client $\to$ Gateway | Configure circadian mode via short address. |
| **26** | Sleep/Wake Mode Response | Gateway $\to$ Client | Acknowledgement. |
| **27** | Sleep/Wake Mode by Group Req | Client $\to$ Gateway | Configure circadian mode via group ID. |
| **28** | Sleep/Wake Mode by Group Resp | Gateway $\to$ Client | Acknowledgement. |
| **29** | Enter Pairing Mode (UART) | Host $\to$ Gateway | Put gateway into BLE provisioning mode. |
| **30** | Enter Pairing Response (UART) | Gateway $\to$ Host | Acknowledgement. |
| **31** | Exit Pairing Mode (UART) | Host $\to$ Gateway | Exit BLE provisioning mode. |
| **32** | Exit Pairing Response (UART) | Gateway $\to$ Host | Acknowledgement. |
| **33** | Send SSID, PWD, Family ID | Gateway $\to$ MCU (UART)| Gateway pushes network config to host MCU. |
| **34** | SSID, PWD, Family ID Response| MCU $\to$ Gateway (UART)| Host MCU confirms receipt of network config. |
| **35** | Connection / Scan Test Request| MCU $\to$ Gateway (UART)| Factory production test for Wi-Fi. |
| **36** | Connection / Scan Test Response| Gateway $\to$ MCU (UART)| Factory test acknowledgement. |
| **37** | Connection / Scan Result | Gateway $\to$ MCU (UART)| Reports Wi-Fi scan/test status. |
| **38** | Set Gateway State Request | UART only ($> \text{v}62042$) | Configure internal gateway settings. |
| **39** | Set Gateway State Response | UART only ($> \text{v}62042$) | Response to state configuration. |
| **40** | Get Gateway State Request | UART only ($> \text{v}62042$) | Query internal gateway status. |
| **41** | Get Gateway State Response | UART only ($> \text{v}62042$) | Returns internal gateway status. |
| **42** | Gateway State Report | UART only ($> \text{v}62042$) | Asynchronous status report from gateway. |
| **43** | Gateway State Report Response | UART only ($> \text{v}62042$) | Acknowledgement. |
| **46** | Reboot Gateway | UDP & UART | Requests gateway system reboot. |
| **47** | Reboot Gateway Response | UDP & UART | Reboot acknowledgement. |
| **48** | Get Network Status Request | UDP & UART | Query Wi-Fi/Cloud connectivity state. |
| **49** | Get Network Status Response | UDP & UART | Returns network status code. |
| **50** | Notify Network Status | Gateway $\to$ MCU (UART)| Async event push on connectivity change. |
| **51** | Notify Network Status Response| MCU $\to$ Gateway (UART)| Acknowledgement of connectivity update. |

> **Critical Note:** Normal transmission of commands **Type 5 through Type 16** requires that the Heartbeat mechanism (Type 3 / Type 4 every 15 seconds) is active and running smoothly.

---

### 2.5 Detailed Message Payload Definitions

#### Type 1: Probe Request (Device Discovery)
- **Data Payload:** Sender's 6-byte MAC address (used as unique controller ID).
- **Packet Structure:**
  - `type`: `0x0001` (Hex: `01 00`)
  - `seq`: 2 bytes
  - `data`: 6-byte client MAC (e.g., `00 00 00 00 00 54`)
- **Hex Example:**
  ```hex
  01 00 a8 3d 00 00 00 00 00 54
  ```

#### Type 2: Probe Response
- **Data Payload:** Gateway's 6-byte MAC address.
- **Hex Example:**
  ```hex
  02 00 a8 3d ec 0b ae a3 ea 15
  ```

#### Type 3: Heartbeat Request
- **Data Payload:** Client MAC address (6 bytes).
- **Hex Example:**
  ```hex
  03 00 1b 99 00 00 00 00 00 54
  ```

#### Type 4: Heartbeat Response
- **Data Payload:** Gateway MAC address (6 bytes).
- **Hex Example:**
  ```hex
  04 00 1b 99 ec 0b ae a3 ea 15
  ```

#### Type 5: Device Config URL Request
- **Data Payload:** None (length = 0).
- **Purpose:** Requests a temporary URL containing the full home configuration (rooms, device endpoints, scenes).
- **Note:** The generated URL is **single-use only**. Subsequent downloads require requesting a new URL.
- **Hex Example:**
  ```hex
  05 00 44 55
  ```

#### Type 6: Device Config URL Response
- **Data Payload:** ASCII/UTF-8 string containing the full download URL (e.g., `http://192.168.31.102:50397/family.dat`).

#### Type 9: Short Address Control Request
- **Data Payload:** `Short Address` (2 bytes, Little-Endian) + `Control Data Payload` (variable).
- **Hex Examples:**
  - Control device with short address `5` (`0x0005` $\to$ `05 00`):
    ```hex
    09 00 30 23 05 00 00
    ```
  - Control device with short address `264` (`0x0108` $\to$ `08 01`):
    ```hex
    09 00 30 23 08 01 00
    ```

#### Type 10: Short Address Control Response
- **Data Payload:** None.

#### Type 11: Scene Control Request
- **Data Payload:** `Scene ID` (3 bytes, Big-Endian).
- **Hex Example:**
  ```hex
  0b 00 ad 7f 00 00 01
  ```

#### Type 12: Scene Control Response
- **Data Payload:** None.

#### Type 13: Group Control Request
- **Data Payload:** `Group Address` (1 byte) + `Category PID` (2 bytes) + `Control Data Payload`.
- **Note:** If the group ID parsed from the home data is $> 255$, it represents a **Virtual Group ID** and must be converted to an actual group ID before transmission (see Section 4.1).
- **Hex Example:** Group `0xDB`, Device Category PID `0x2AA8`, Control payload `0x00`:
  ```hex
  0d 00 90 7f db 2a a8 00
  ```

#### Type 14: Group Control Response
- **Data Payload:** None.

#### Type 15: Device Telemetry / State Report Request
Sent asynchronously from the gateway to the controller when device states change or in response to a status trigger (Type 17).

- **Single Device Report Example:**
  ```hex
  0f 00 ca 78 16 c0 f1 5e f5 08 00 60 7f 00 00 ff 00 00 00 00 00 00 00 00 00 00 00
  ```
  - `0f 00`: Message Type 15 (Little-Endian).
  - `ca 78`: Sequence number.
  - `16`: Payload chunk length (22 bytes).
  - `c0`: Address mode indicator.
    - `0xC0` indicates the short address is $\le 255$.
    - Values $> \text{0xC0}$ (e.g., `0xC1`) indicate a device with short address $> 256$. The lowest 4 bits represent the higher-order address bits. For example, `C1` followed by short address byte `01` yields short address $(0\text{x}01 \ll 8) + 0\text{x}01 = 257$.
  - Next 3 bytes (`f1 5e f5`): Internal metadata.
  - Device Short Address byte: `0x08`.
  - Next 2 bytes: Reserved (`00 60`).
  - Remaining 15 bytes (`7f 00 00 ff ...`): BroadLink standard device state payload.

- **Multiple Device Report Example:**
  Multiple 22-byte (`0x16`) frames can be concatenated inside a single packet:
  ```hex
  0f 00 0a cc 16 c0 06 5e 66 12 00 30 00 00 ... 16 c0 07 5e 68 13 00 30 01 00 ...
  ```

#### Type 16: Device Telemetry Report Response
Acknowledges receipt of Type 15 telemetry. Must return the exact `seq` from the report packet:
```hex
10 00 12 12
```

#### Type 17: Trigger Device Status Report Request
Polls sub-devices to report their current status. Non-sensor devices typically do not report telemetry autonomously unless triggered by this command.

- **Payload Structure:**
  - `delay_max` (1 byte): Maximum random reporting delay backoff.
  - `start_addr_msb` (1 byte): Most significant byte of the start address (for devices with address $\ge 256$).
  - `start_addr_lsb` (1 byte): Least significant byte of the start address.
  - `mask` (13 bytes): Bitmask representing target devices. Each bit corresponds to one device offset from `start_addr`. A bit set to `1` queries that device.

- **Delay Timing Formula:**
  $$\text{Delay} = (\text{rand}() \pmod{\text{delay\_max} + 1}) \times 15\text{ ms}$$
  The maximum possible delay is $255 \times 15\text{ ms} = 3825\text{ ms}$. If `delay_max` is 0, the device responds immediately.  
  *(Note: $\text{delay\_max} + 1$ must be a power of 2).*

- **Mask Capability:** 13 bytes $\times 8\text{ bits} = 104$ devices per packet. If target devices span an address range $> 104$, multiple requests must be issued.

- **Hex Example (Query Short Address 8):**
  ```hex
  11 00 11 22 ff 00 08 01 00 00 00 00 00 00 00 00 00 00 00 00
  ```
  - `delay_max`: `0xFF`
  - `start_addr`: `0x0008`
  - `mask`: `01 00 00 00 ...` (Bit 0 set, representing $8 + 0 = 8$).

#### Type 18: Trigger Device Status Report Response
- **Data Payload:** None.

#### Type 19: Set Temporary Group Request
Creates an ephemeral group for synchronized, low-latency control. Devices automatically drop the temporary group when a new cookie is encountered.

- **Structure (Packed):**
  ```c
  uint8_t  group_id;    /* Temporary Group ID: 225 - 255 */
  uint16_t start_addr;  /* Start address (Little-Endian) */
  uint16_t cookie;      /* Unique identifier generated per transaction */
  uint8_t  mask[13];    /* 104-bit device selection mask */
  ```

- **Hex Example:**
  ```hex
  13 00 02 b1 e6 04 01 09 03 1f 00 00 00 00 00 00 00 00 00 00 00 00
  ```
  - `group_id`: `0xE6` (230)
  - `start_addr`: `0x0104` (260)
  - `cookie`: `0x0309`
  - `mask`: `0x1F` (5 bits set: targets addresses 260, 261, 262, 263, 264).

#### Type 20: Set Temporary Group Response
- **Data Payload:** None.

---

### 2.6 Serial & Diagnostic Commands (UART / UDP)

#### Type 33: Provisioning Configuration Push (Gateway $\to$ Host MCU)
Transmitted over UART after network pairing. Formatted as JSON:
```json
{
  "ssid": "MyWiFiNetwork",
  "pwd": "MyPassword123",
  "familyid": "5a1996cb8082d0680674838701549ba9_user_vt"
}
```
If the MCU does not acknowledge with **Type 34**, the gateway retransmits up to 9 times (1 packet per second).

#### Type 35: Factory Wi-Fi Scan / Connection Test
- **Payload (JSON):**
  ```json
  {
    "ssid": "TestSSID",
    "pwd": "TestPassword",
    "mode": 0
  }
  ```
  - `mode`: `0` = Scan Only; `1` = Attempt Association.

#### Type 37: Factory Test Result
- **Payload:** 1 byte status code (`0` = Success, Non-zero = Error).

#### Type 46 & 47: Gateway Reboot
- **Request (Type 46):** `2e 00 <seq>` (triggers system reboot).
- **Response (Type 47):** `2f 00 <seq>` (reboot acknowledged).

#### Type 48 & 49: Network Status Query
- **Request (Type 48):** Query connectivity state.
- **Response (Type 49) / Async Notification (Type 50):** Status payload (1 byte):
  - `1`: In Wi-Fi pairing mode.
  - `2`: Connecting to local Wi-Fi router.
  - `3`: Associated with router; establishing connection to BroadLink Cloud.
  - `4`: Fully connected to Cloud.
- **Type 51:** Acknowledgement of Type 50 from MCU to Gateway.

---

## 3. Local LAN Family Data Sharing

Smart display control panels (e.g., 4-inch or 8-inch touch screens) can synchronize family data directly across the local LAN without contacting the cloud. The display device acts as a UDP Server listening on a local port.

```
Smart Display Panel (UDP Server)                       Mobile App (Client)
        |                                                       |
        |<======== Periodic Discovery Request (Every 3s) =======|
        |======== Device Discovery Response ===================>|
        |                                                       |
        |                                         [User prompts authorization]
        |<-------- Device Authorization Request ----------------|
        |--------- Authorization Response --------------------->|
        |                                                       |
        |<-------- Data Chunk Transfers (1024B) ----------------|
        |--------- Chunk ACK / Mask Response ------------------>|
        |                                                       |
```

### 3.1 Packet Header Structure

All LAN sharing frames use the binary header below:

```c
typedef struct {
    uint32_t magic;     /* Fixed value: 0x5A5AA5A5 */
    uint16_t msgtype;   /* Message Type ID */
    uint16_t seq;       /* Sequence Number */
    uint16_t checksum;  /* Checksum over header, opt header, and payload */
    uint8_t  optlen;    /* Optional header length (Reserved, set to 0) */
    uint8_t  version;   /* Protocol Version (Currently 0) */
} net_head_t;
```

#### Checksum Algorithm
The initial checksum seed is `0xBEAF`:
```c
uint16_t getcsum(uint8_t *data, int len)
{
    uint16_t csum_cal = 0xBEAF;
    int i;
    for (i = 0; i < len; i++) {
        csum_cal += data[i];
    }
    return csum_cal;
}
```

#### LAN Sharing Message Types (`msgtype`)

| `msgtype` | Description | Security |
| :---: | :--- | :--- |
| `0` | Local Discovery Request (UDP Broadcast) | Plaintext |
| `1` | Local Discovery Response | Plaintext |
| `2` | Device Authorization Request | AES Encrypted |
| `3` | Device Authorization Response | AES Encrypted |
| `12`| Data Sharing Request | Plaintext |
| `13`| Data Sharing Response | Plaintext |
| `14`| Chunk Data Block Transfer Request | Plaintext |
| `15`| Chunk Data Block Transfer Response | Plaintext |

---

### 3.2 Security and AES Encryption

Where encryption is specified, **AES-128-CBC** is used with **PKCS#5 / PKCS#7** padding.

#### Public Key and Initialization Vector (IV)
Used exclusively during the device authorization phase:
```c
const uint8_t aes_public_iv[] = {
    0xea, 0xaa, 0xaa, 0x3a, 0xbb, 0x58, 0x62, 0xa2,
    0x19, 0x18, 0xb5, 0x77, 0x1d, 0x16, 0x15, 0xaa
};

const uint8_t aes_public_key[] = {
    0xac, 0xcf, 0x8b, 0x02, 0x76, 0x5c, 0x15, 0x13,
    0x3f, 0xe9, 0x9e, 0x23, 0x09, 0x76, 0x28, 0x34
};
```

---

### 3.3 Device Discovery Payload (Types 0 & 1)

- **Request:** Header with `msgtype = 0`.
- **Response (`msgtype = 1`):** JSON payload:
  ```json
  {
    "mac": "ec0baea3ea15",
    "ip": "192.168.1.100",
    "name": "Living Room Panel",
    "pid": "000000000000000000000000eca90000"
  }
  ```

---

### 3.4 Device Authorization (Types 2 & 3)

- **Request (`msgtype = 2`):** Encrypted JSON:
  ```json
  {
    "familyKey": "a1b2c3d4e5f60718"
  }
  ```
- **Response (`msgtype = 3`):** Encrypted JSON:
  ```json
  {
    "status": 0
  }
  ```
  *(Status `0` indicates successful authorization).*

---

### 3.5 Chunk Block Transfer Protocol (Types 14 & 15)

Used to transmit large payloads by splitting them into smaller frames.

#### Block Transfer Header
| Field | Size | Description |
| :--- | :---: | :--- |
| **MsgID** | 4 Bytes | Transaction ID generated randomly from a local seed. |
| **Len** | 2 Bytes | Length of the subsequent body payload. |
| **OptType** | 1 Byte | `0` = POST; `1` = GET. |
| **ResType** | 1 Byte | Resource Type: `0` = Family Data; `255` = Test Data. |

- **POST Request Body:**
  - `total_chunks` (1 Byte): Total number of segments.
  - `chunk_index` (1 Byte): Index of the current chunk (0-indexed).
  - `chunk_data` ($N$ Bytes): Segment payload (typically 1024 bytes per chunk except for the final segment).
- **POST Response Body:**
  - `mask` ($N$ Bytes): Bitmask acknowledging received chunks (`1` = received, `0` = missing).

---

### 3.6 Family Data Format

The reconstructed payload (either downloaded via the HTTP URL from Type 6 or reassembled from local block sharing) is a JSON object containing Base64-encoded strings under specific data tags:

```json
{
  "status": 0,
  "data": [
    {
      "did": "5a1996cb8082d0680674838701549ba9_user_vt",
      "dataList": [
        {
          "mtag": "devlist",
          "data": "<Base64 Encoded Device Array>"
        },
        {
          "mtag": "familyInfo",
          "data": "<Base64 Encoded Family Metadata>"
        },
        {
          "mtag": "grouplist",
          "data": "<Base64 Encoded Group Array>"
        },
        {
          "mtag": "scenelist",
          "data": "<Base64 Encoded Scene Array>"
        }
      ]
    }
  ]
}
```

#### Decoded `devlist` Schema
```json
[
  {
    "aeskey": "5aa5eca900d9cbd7a8cbbdf559441444",
    "devicetypeflag": 0,
    "devname": "Gateway ea5f",
    "did": "00000000000000000000ec0baea3ea5f",
    "pid": "000000000000000000000000eca90000",
    "room": "Whole House",
    "roomId": 0,
    "terminalid": 1,
    "version": ""
  },
  {
    "blecatetory": "DOOR_SENSOR",
    "bletoken": "7f1b9555",
    "cnt": 0,
    "devicetypeflag": 0,
    "devname": "Door Sensor c528",
    "did": "00000000000000000000ec0baea3ea5f",
    "extendInfo": "{\"vGroups\":[]}",
    "ignoreflag": false,
    "pid": "000000000000000000000000eca90000",
    "room": "Whole House",
    "roomId": 0,
    "sdid": "00000000000000000000aabbcc00c528",
    "shortaddr": "5",
    "spid": "000000000000000000000000f1a90000",
    "terminalid": 1,
    "version": "4.1.0.2056.15"
  }
]
```

#### Supported Device Categories (`blecatetory`)

| Category Code | Description | Functional Group |
| :--- | :--- | :--- |
| `RGBCWLIGHT` | RGBCW Color + Tunable White Light | Lighting |
| `RGBWLIGHT` | RGBW 4-Channel Light | Lighting |
| `RGBLIGHT` | RGB 3-Channel Light | Lighting |
| `CWLIGHT` | Dual-Channel Tunable White Light | Lighting |
| `LIGHT` | Single-Channel Dimmer / White Light | Lighting |
| `SWITCH` | Wall / Relay Switch Panel | Switching |
| `CURTAIN` | Motorized Curtain / Blind Controller | Motorized |
| `BLEAC` | Bluetooth Air Conditioning / Thermostat | Climate Control |
| `GATEWAY` | Central Mesh Gateway | Hub |
| `PANEL` | Scenario / Push-button Switch Panel | Trigger Device |
| `DOOR_SENSOR` | Contact / Magnetic Door Sensor | Sensor |
| `PIR_SENSOR` | Passive Infrared Motion Sensor | Sensor |
| `FLOOD_SENSOR` | Water Leakage / Immersion Sensor | Sensor |
| `TEMPERATURE_HUMIDITY_SENSOR` | Environmental Temp/RH Sensor | Sensor |
| `SMOKE_SENSOR` | Smoke / Fire Sensor | Sensor |
| `GAS_SENSOR` | Combustible Gas Sensor | Sensor |

---

#### Decoded `familyInfo` Schema
```json
{
  "name": "My Home",
  "roomlist": [
    { "roomId": 0, "roomName": "Whole House" },
    { "roomId": 1, "roomName": "Living Room" },
    { "roomId": 2, "roomName": "Master Bedroom" },
    { "roomId": 3, "roomName": "Second Bedroom" },
    { "roomId": 4, "roomName": "Dining Room" },
    { "roomId": 5, "roomName": "Study" }
  ],
  "updateTime": 1666004010
}
```

#### Decoded `grouplist` Schema
```json
[
  {
    "blecatetory": "RGBCWLIGHT",
    "groupId": 256,
    "groupName": "Living Room Lights",
    "ignoreflag": false,
    "roomId": 1,
    "roomName": "Living Room"
  }
]
```

#### Decoded `scenelist` Schema
```json
[
  {
    "backColor": 1,
    "bletoken": "7f1b9555",
    "ignoreflag": false,
    "image": "icon_scene_all_on",
    "moduledev": [
      {
        "content": "{}",
        "did": "00000000000000000000ec0baea3ea5f",
        "sdid": "1"
      }
    ],
    "moduleid": "1",
    "name": "Turn All On",
    "room": "Whole House",
    "roomId": 0
  }
]
```

---

## 4. Technical Reference Specifications

### 4.1 Group ID (`groupID`)

A `groupID` is a 1-byte identifier ranging from **0 to 255**. BroadLink uses groups in four contexts:
1. **Room Grouping:** Rooms operate as default hardware groups.
2. **Fixed Grouping:** User-defined device groups bound via the application.
3. **Temporary Grouping:** Ephemeral groups created on the fly for synchronized animations or transitions.
4. **Virtual Grouping:** Auto-generated by the "e-Control Home" app for aggregate control of all devices of a given category within a room.

#### Virtual Group ID Conversion
A virtual group ID is an integer consisting of two bytes:
- **Upper Byte:** Product major category.
- **Lower Byte:** Target room `groupID`.

*Example:* All lights in the Living Room (Room ID = `0x01`). The lighting category ID is `0x01`. Combining them produces:
$$\text{Virtual Group ID} = (0\text{x}01 \ll 8) \mid 0\text{x}01 = 0\text{x}0101 = 257$$

To issue a command to a Virtual Group using **Type 13 (Group Control)**:
- Extract the real target `groupID`:
  $$\text{Target Group ID} = \text{Virtual Group ID} \ \& \ 0\text{xFF}$$
- Supply the corresponding **Category PID** (see table below).

| Category ID | Category Name | Category PID |
| :---: | :--- | :---: |
| `0` | Scenes | None |
| `1` | Lights | `0x2AA8` |
| `2` | Curtains | `0xEBA9` |
| `3` | Relay Switches | `0xC3A9` |
| `4` | Thermostats / AC | `0xECAA` |
| `5` | Gateway | Reserved |

---

### 4.2 Scene ID Format

A Scene ID consists of **3 consecutive bytes**:

| Byte 0 | Byte 1 | Byte 2 |
| :---: | :---: | :---: |
| `GroupID` | `Device Type` | `Scene Sequence Number` |
| Room `groupID` where the scene resides | Fixed at `0x00` | Index of the scene in the home |

Scenes fall into two types:
- **Default System Scenes:** 13 factory-defined presets (e.g., Turn All On, Turn All Off).
- **Custom User Scenes:** User-configured automations.

---

### 4.3 Product ID (PID) Architecture

Devices are classified by two types of PIDs:
- **Primary PID (`主PID`):** Uniquely identifies a specific hardware model and its detailed capabilities.
- **Parent / Category PID (`父PID`):** Identifies the broader functional category. Used by controllers, switches, and panels to execute batch control commands across mixed models of the same class.

#### Parent PID Mapping Table

| Class ID | Product Category | Parent PID (Big-Endian Hex) |
| :---: | :--- | :---: |
| `0` | Scenes | None |
| `1` | Lighting Fixtures | `2A A8` |
| `2` | Motorized Curtains | EB A9 |
| `3` | Relay Switches | C3 A9 |
| `4` | AC / Climate Control | EC AA |
| `5` | Gateway | Reserved |