import hashlib
import sys

print (hashlib.sha256(sys.argv[1]).hexdigest())