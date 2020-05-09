
import random
"""
http://stackoverflow.com/questions/1051949/map-incrementing-integer-range-to-six-digit-base-26-max-but-unpredictably/1052896#1052896
"""
# generate a random bit order
# you'll need to save this mapping permanently, perhaps just hardcode it
# map how ever many bits you need to represent your integer space
mapping = range(28)
mapping.reverse()

#random.shuffle(mapping)

# alphabet for changing from base 10
chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

def get_id(n):
	return decode(debase(n))

def get_code(n):
	return enbase(encode(n))
# shuffle the bits
def encode(n):
    result = 0
    for i, b in enumerate(mapping):
        b1 = 1 << i
        b2 = 1 << mapping[i]
        if n & b1:
            result |= b2
    return result

# unshuffle the bits
def decode(n):
    result = 0
    for i, b in enumerate(mapping):
        b1 = 1 << i
        b2 = 1 << mapping[i]
        if n & b2:
            result |= b1
    return result

# change the base
def enbase(x):
    n = len(chars)
    if x < n:
        return chars[x]
    return enbase(x/n) + chars[x%n]

# go back to base 10
def debase(x):
    n = len(chars)
    result = 0
    for i, c in enumerate(reversed(x)):
        result += chars.index(c) * (n**i)
    return result
"""
# test it out
for a in range(10):
    b = encode(a)
    c = get_code(a)
    d = debase(c)
    e = get_id(c)


	#while len(c) < 7:
     #   c = ' ' + c
    print '%6d\t%6d\t%s\t%6d\t%6d' % (a, b, c, d, e)
"""

