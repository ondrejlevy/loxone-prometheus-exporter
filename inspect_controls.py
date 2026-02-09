"""Inspect Loxone control structure to find description/details field."""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import struct
import urllib.parse
import zlib

import aiohttp
import websockets
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import HMAC as CryptoHMAC, SHA256 as CryptoSHA256
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad


async def recv_text(ws):
    msg = await ws.recv()
    if isinstance(msg, bytes):
        msg = await ws.recv()
    if isinstance(msg, bytes):
        return msg.decode("utf-8", errors="replace")
    return msg


async def authenticate_ws(ws, host, port, username, password):
    """Full token auth."""
    # Fetch public key via HTTP
    url = f"http://{host}:{port}/jdev/sys/getPublicKey"
    auth = aiohttp.BasicAuth(username, password)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, auth=auth) as resp:
            text = await resp.text()
            data = json.loads(text)
            raw_key = data["LL"]["value"].strip()
            raw_key = raw_key.replace("-----BEGIN CERTIFICATE-----", "-----BEGIN PUBLIC KEY-----")
            raw_key = raw_key.replace("-----END CERTIFICATE-----", "-----END PUBLIC KEY-----")
            if "-----BEGIN PUBLIC KEY-----" in raw_key:
                parts = raw_key.split("-----BEGIN PUBLIC KEY-----")
                body = parts[1].split("-----END PUBLIC KEY-----")[0].strip()
                body_clean = body.replace("\n", "").replace("\r", "").replace(" ", "")
                lines = [body_clean[i:i+64] for i in range(0, len(body_clean), 64)]
                pub_key_pem = "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"

    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    enc_salt = secrets.token_bytes(16).hex()

    # Key exchange
    rsa_key = RSA.import_key(pub_key_pem)
    cipher_rsa = PKCS1_v1_5.new(rsa_key)
    session_key = f"{aes_key.hex()}:{aes_iv.hex()}"
    encrypted_session = cipher_rsa.encrypt(session_key.encode("utf-8"))
    b64_session = base64.b64encode(encrypted_session).decode("ascii")
    await ws.send(f"jdev/sys/keyexchange/{b64_session}")
    await recv_text(ws)

    # getkey2
    await ws.send(f"jdev/sys/getkey2/{username}")
    resp = await recv_text(ws)
    ll = json.loads(resp).get("LL", {})
    value = ll.get("value", {})
    if isinstance(value, str):
        value = json.loads(value)
    raw_key_hex = value["key"]
    raw_salt_hex = value["salt"]

    # Compute credential hash
    key_bytes = bytes.fromhex(raw_key_hex)
    pwd_hash = hashlib.sha256(f"{password}:{raw_salt_hex}".encode("utf-8")).hexdigest().upper()
    digester = CryptoHMAC.new(key_bytes, f"{username}:{pwd_hash}".encode("utf-8"), CryptoSHA256)
    cred_hash = digester.hexdigest()

    # Encrypt and send getjwt
    cmd = f"jdev/sys/getjwt/{cred_hash}/{username}/2/edfc5f9a-df3f-4cad-9dddcdc42c732b82/loxprom"
    command_string = f"salt/{enc_salt}/{cmd}\x00"
    padded_bytes = pad(command_string.encode("utf-8"), 16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=aes_iv)
    encrypted = cipher.encrypt(padded_bytes)
    b64 = base64.b64encode(encrypted).decode("utf-8")
    enc_cmd = urllib.parse.quote(b64)

    await ws.send(f"jdev/sys/enc/{enc_cmd}")
    resp = await recv_text(ws)
    ll = json.loads(resp).get("LL", {})
    code = str(ll.get("Code", ll.get("code", "")))
    assert code == "200", f"Auth failed with code {code}"


async def main():
    host, port = "192.168.90.17", 80
    username, password = "Ondra", "421563"
    uri = f"ws://{host}:{port}/ws/rfc6455"
    async with websockets.connect(uri) as ws:
        await authenticate_ws(ws, host, port, username, password)
        print("Auth OK\n")

        # Request structure file
        await ws.send("data/LoxAPP3.json")

        # Skip header frames
        await ws.recv()  # first header
        await ws.recv()  # second header

        # Get text frame
        frame = await ws.recv()
        data = json.loads(frame)

        # Inspect first few controls
        controls = data.get("controls", {})
        print(f"Total controls: {len(controls)}\n")
        print("=" * 80)
        
        for i, (uuid, ctrl) in enumerate(list(controls.items())[:5]):
            print(f"\nControl {i+1}: {uuid}")
            print(f"  Keys: {list(ctrl.keys())}")
            for key, value in ctrl.items():
                if key not in ["states", "subControls", "details"]:
                    print(f"  {key}: {value}")
            if "details" in ctrl:
                print(f"  details: {ctrl['details']}")
            print()

        # Look for any control with 'details' or 'description' field
        print("\n" + "=" * 80)
        print("Searching for 'details' or 'description' fields...")
        print("=" * 80)
        
        has_details = []
        has_desc = []
        
        for uuid, ctrl in controls.items():
            if "details" in ctrl:
                has_details.append((uuid, ctrl.get("name", ""), ctrl.get("type", ""), ctrl.get("details", {})))
            if "description" in ctrl:
                has_desc.append((uuid, ctrl.get("name", ""), ctrl.get("type", ""), ctrl.get("description", "")))
        
        if has_details:
            print(f"\nFound {len(has_details)} controls with 'details' field:")
            for uuid, name, ctype, details in has_details[:10]:
                print(f"  {name} ({ctype})")
                print(f"    UUID: {uuid}")
                print(f"    details: {details}")
                print()
        else:
            print("\n  No controls with 'details' field found")
        
        if has_desc:
            print(f"\nFound {len(has_desc)} controls with 'description' field:")
            for uuid, name, ctype, desc in has_desc[:10]:
                print(f"  {name} ({ctype})")
                print(f"    UUID: {uuid}")
                print(f"    description: {desc}")
                print()
        else:
            print("\n  No controls with 'description' field found")

        # Save full structure for manual inspection
        with open("loxone_structure.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nFull structure saved to loxone_structure.json")

asyncio.run(main())
