import uuid
import binascii 
import hashlib
import re

def short_hash(len=5):
    result = hashlib.md5(str(uuid.uuid1())).hexdigest()
    result = binascii.unhexlify(result)
    result = result.encode('base64')
    result = re.sub("[^A-Za-z0-9]", "", result)
    return result[0:len]