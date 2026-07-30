#!/usr/bin/env python3

## import GAP release archives into a git repository using git-fast-import
##
##  Based on import-zips.py from git/contrib/
##
## For example:
##
##  mkdir project; cd project; git init
##  python import-zips.py *.zip
##  git log --stat import-zips

import subprocess
from sys import argv, exit, hexversion, stderr
#from time import mktime
#from zipfile import ZipFile
import tarfile

if hexversion < 0x03060000:
    stderr.write("import-gap-releases.py: requires Python 3.6.0 or later.\n")
    exit(1)

gap_releases = [
    ("4.4.4", "gap44/tar.gz/gap4r4p4.tar.gz"),
    ("4.4.5", "gap44/tar.gz/gap4r4p5.tar.gz"),
    ("4.4.6", "gap44/tar.gz/gap4r4p6.tar.gz"),
    ("4.4.7", "gap44/tar.gz/gap4r4p7.tar.gz"),
    ("4.4.8", "gap44/tar.gz/gap4r4p8.tar.gz"),
    ("4.4.9", "gap44/tar.gz/gap4r4p9.tar.gz"),
    ("4.4.10", "gap44/tar.gz/gap4r4p10.tar.gz"),
    ("4.4.11", "gap44/tar.gz/gap4r4p11.tar.gz"),
    ("4.4.12", "gap44/tar.gz/gap4r4p12.tar.gz"),
    ("4.5.4", "gap45/tar.gz/gap4r5p4_2012_06_04-23_02.tar.gz"),
    ("4.5.4a", "gap45/tar.gz/gap4r5p4_2012_06_16-17_03.tar.gz"),
    ("4.5.5", "gap45/tar.gz/gap4r5p5_2012_07_16-17_17.tar.gz"),
    ("4.5.6", "gap45/tar.gz/gap4r5p6_2012_09_16-01_02.tar.gz"),
    ("4.5.6a", "gap45/tar.gz/gap4r5p6_2012_11_04-18_46.tar.gz"),
    ("4.5.6b", "gap45/tar.gz/gap4r5p6_2012_12_09-19_28.tar.gz"),
    ("4.5.7", "gap45/tar.gz/gap4r5p7_2012_12_14-17_45.tar.gz"),
    ("4.6.2", "gap46/tar.gz/gap4r6p2_2013_02_02-01_00.tar.gz"),
    ("4.6.3", "gap46/tar.gz/gap4r6p3_2013_03_18-17_40.tar.gz"),
    ("4.6.4", "gap46/tar.gz/gap4r6p4_2013_05_04-16_36.tar.gz"),
    ("4.6.5", "gap46/tar.gz/gap4r6p5_2013_07_20-20_02.tar.gz"),
    ("4.7.2", "gap47/tar.gz/gap4r7p2_2013_12_01-10_17.tar.gz"),
    ("4.7.3", "gap47/tar.gz/gap4r7p3_2014_02_15-19_41.tar.gz"),
    ("4.7.4", "gap47/tar.gz/gap4r7p4_2014_02_20-01_21.tar.gz"),
    ("4.7.5", "gap47/tar.gz/gap4r7p5_2014_05_24-20_02.tar.gz"),
    ("4.7.6", "gap47/tar.gz/gap4r7p6_2014_11_15-20_02.tar.gz"),
    ("4.7.7", "gap47/tar.gz/gap4r7p7_2015_02_13-15_29.tar.gz"),
    ("4.7.8", "gap47/tar.gz/gap4r7p8_2015_06_09-20_27.tar.gz"),
    ("4.7.9", "gap47/tar.gz/gap4r7p9_2015_11_29-20_35.tar.gz"),
    ("4.8.2", "gap48/tar.gz/gap4r8p2_2016_02_20-18_51.tar.gz"),
    ("4.8.3", "gap48/tar.gz/gap4r8p3_2016_03_19-22_17.tar.gz"),
    ("4.8.4", "gap48/tar.gz/gap4r8p4_2016_06_04-12_41.tar.gz"),
    ("4.8.5", "gap48/tar.gz/gap4r8p5_2016_09_25-11_49.tar.gz"),
    ("4.8.6", "gap48/tar.gz/gap4r8p6_2016_11_12-14_25.tar.gz"),
    ("4.8.7", "gap48/tar.gz/gap4r8p7_2017_03_24-21_21.tar.gz"),
    ("4.8.8", "gap48/tar.gz/gap4r8p8_2017_08_20-15_12.tar.gz"),
    ("4.8.9", "gap48/tar.gz/gap4r8p9_2017_12_18-23_44.tar.gz"),
    ("4.8.10", "gap48/tar.gz/gap4r8p10_2018_01_15-13_02.tar.gz"),
    ("4.9.1", "gap-4.9/tar.gz/gap-4.9.1.tar.gz"),
    ("4.9.2", "gap-4.9/tar.gz/gap-4.9.2.tar.gz"),
    ("4.9.3", "gap-4.9/tar.gz/gap-4.9.3.tar.gz"),
    ("4.10.0", "gap-4.10/tar.gz/gap-4.10.0.tar.gz"),
    ("4.10.1", "gap-4.10/tar.gz/gap-4.10.1.tar.gz"),
    ("4.10.2", "gap-4.10/tar.gz/gap-4.10.2.tar.gz"),
    ("4.11.0", "gap-4.11/tar.gz/gap-4.11.0.tar.gz"),
    ("4.11.1", "gap-4.11/tar.gz/gap-4.11.1.tar.gz"),
    ("4.12.0", "gap-4.12/tar.gz/gap-4.12.0.tar.gz"),
    ("4.12.1", "gap-4.12/tar.gz/gap-4.12.1.tar.gz"),
    ("4.12.2", "gap-4.12/tar.gz/gap-4.12.2.tar.gz"),
]

branch_ref = 'refs/heads/import-zips'
committer_name = 'GAP'
committer_email = 'support@gap-system.org'

#fast_import = popen('git fast-import --quiet', 'wb')
fast_import_process = subprocess.Popen(['/usr/bin/git', 'fast-import', '--quiet'], stdin=subprocess.PIPE)
fast_import = fast_import_process.stdin

def spin(i):
    print('|/-\\'[i % 4], '\r', end='', flush=True)

def println(str):
    str += '\n'
    fast_import.write(str.encode('utf-8'))

def print_data(data, size = None):
    if size == None:
        size = len(data)
    println('data ' + str(size))
    written = fast_import.write(data)
    assert written == size
    println('')

for (version,filename) in gap_releases:
    commit_time = 0
    next_mark = 1
    common_prefix = None
    mark = dict()
    mode = dict()
    tag = 'v' + version

    print("Importing",filename,"version",version)

    with tarfile.open("/srv/www/www-gap-files/data/http/"+filename) as archive:
        for member in archive:
            name = member.name
            if member.isdir():
                continue
            if name.endswith(".dvi"):
                continue
            if name.endswith(".pdf"):
                continue
            if name.endswith("pkg/agt/doc/mathjax"):  # skip broken symlink from AGT
                continue
            spin(next_mark)

            if commit_time < member.mtime:
                commit_time = member.mtime

            if common_prefix == None:
                common_prefix = name[:name.rfind('/') + 1]
            else:
                while not name.startswith(common_prefix):
                    last_slash = common_prefix[:-1].rfind('/') + 1
                    common_prefix = common_prefix[:last_slash]

            if member.issym():
                mode[name] = 0o120000
            else:
                mode[name] = member.mode
            
            mark[name] = ':' + str(next_mark)
            next_mark += 1

            println('blob')
            println('mark ' + mark[name])
            if member.issym():
                assert member.size == 0
                print_data(member.linkname.encode('utf-8'))
            else:
                print_data(archive.extractfile(member).read(), member.size)
    print('\r \r', end='', flush=True)

    committer = '%s <%s> %d +0000' % (committer_name, committer_email, commit_time)

    println('commit ' + branch_ref)
    println('committer ' + committer)
    print_data(('Version ' + version + '\n').encode('utf-8'))

    println('deleteall')
    for name in mark.keys():
        if (mode[name] & 0o777000) == 0o120000:
            m = "120000"
        elif (mode[name] & 0o000111) != 0:  # any executable bit set?
            m = "100755"
        else:
            m = "100644"
        println('M %s %s %s' % (m, mark[name], name[len(common_prefix):]))

    # Create (annotated) tag
    # TODO: use 'reset' instead of light-weight tag?
    #   reset refs/tags/938
    #   from :938     resp 'from $branch_ref'
    # TODO: use current date?
#     println('tag ' + tag)
#     println('from ' + branch_ref)
#     println('tagger ' + committer)
#     print_data('Package ' + basename + '\n')
#     println('')
    println('reset refs/tags/' + tag)
    println('from ' + branch_ref)
    println('')

if fast_import.close():
    print("There was an error closing the pipe")
    exit(1)

if fast_import_process.wait() != 0:
    print("There was an error exiting git")
    exit(1)
