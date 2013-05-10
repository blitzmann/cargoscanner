fitShop
========================
Ever thought "I want to buy 3 Slicer's with this fit, one Slicer with this fit, 2 Ruptures with this fit, and 5 Nidhoggurs* with this fit"? It takes time and patience to sit there and pul up each fitting, find it in the market, and then purchase them. This tool aims to help smooth out the process a bit by consolidating all the items that the ships share into one shopping list with handy links to their market window. 

I was originally going to write this from scratch in PHP, however I decided against that and as such this has become my first Python web application. It is a forked version of Evepraisal's source code, modified (honestly, hacked together) to support a few new features. I figured I would start with a solid codebase and make tweaks along the way, since as I'm learning as I go. This project uses EMDR coupled with Redis to provide pricing data, however I've left the original options of EVE-Central + Memcache in case needed.

Requirements
============
* Python >= 2.6
* Flask
* Redis (recommended) or Memcache
* (optional) EMDR consumer script (this will kill your bandwidth, but it's oh so delicious)

First Run
=========
First, you need to download the source.
```
git clone https://github.com/blitzmann/fitShop.git
cd fitShop
```

Install requirements
```
pip install -r requirements.txt
```

Start the app
```
python fitShop.py
```

Deployment
==========
I'll let you know when I figure it out

License
=======
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

CCP Copyright Notice
====================
EVE Online and the EVE logo are the registered trademarks of CCP hf. All rights are reserved worldwide. All other trademarks are the property of their respective owners. EVE Online, the EVE logo, EVE and all associated logos and designs are the intellectual property of CCP hf. All artwork, screenshots, characters, vehicles, storylines, world facts or other recognizable features of the intellectual property relating to these trademarks are likewise the intellectual property of CCP hf. CCP hf. has granted permission to Evepraisal.com to use EVE Online and all associated logos and designs for promotional and information purposes on its website but does not endorse, and is not in any way affiliated with, Evepraisal.com. CCP is in no way responsible for the content on or functioning of this website, nor can it be liable for any damage arising from the use of this website.
