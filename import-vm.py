#!/usr/bin/env python3

import sys
import subprocess
import os
import yaml

config = None

def parse_search(lines):
    elements = []
    pos = 0
    for line in lines:
        pos += 1
        if pos == 2:
            titles = line.split()
        elif pos == 3:
            hyphens = line.split()
            lens = []
            for group in hyphens:
                lens.append(len(group)+2)
        elif pos > 3:
            element = {}
            pos = 0
            for i in range(len(titles)):
                datalen = lens[i]
                element[titles[i]] = line[pos:pos+datalen].strip()
                pos += datalen
            elements.append(element)
    return elements

def run_ovftool(vm, vapp_name):
    result = subprocess.run(["ovftool/ovftool", "vcloud://{0}:{1}@{2}?org={3}&vdc={4}&catalog={5}&vappTemplate={6}".format(config['login'], config['password'], config['vcloud_url'], config['org'], config['vdc'], config['catalog'], vapp_name), "{0}/{0}.ovf".format(vm)], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))

def get_hidden_vapp_name(vm):
    result = subprocess.run(["vcd", "search", "vm", "-f", "name=={0};isVAppTemplate==false".format(vm)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))
    elements = parse_search(result.stdout.splitlines())
    if len(elements) != 1:
        raise Exception("search for vm {0} produced {1} results, expecting exactly 1. details: {2}, {3}".format(vm,len(elements),elements,result.stdout))
    #print(elements)
    return elements[0][b'containerName'].decode()

def vcd_login():
    result = subprocess.run(["vcd", "login", config['vcloud_url'], config['org'], config['login'], "-p", config['password']], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))
    result = subprocess.run(["vcd", "vdc", "use", config['vdc']], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))

def remove_ovf_collection(vm):
    new = "{0}/{0}.ovf".format(vm)
    old = "{0}/{0}.ovf.old".format(vm)
    os.rename(new, old)
    skip = False
    with open(new, 'w') as new_file:
        with open(old, 'r') as old_file:
            for line in old_file:
                if line.strip().startswith("<ovf:VirtualSystemCollection ") or line.strip().startswith("</ovf:VirtualSystemCollection>") :
                    skip = True
                elif line.strip().startswith("<ovf:VirtualSystem ") or line.strip().startswith("</ovf:Envelope>"):
                    skip = False
                if not skip:
                    new_file.write(line)
    os.remove(old)

def upload_to_bucket(vm):
    print("* uploading to bucket")
    result = subprocess.run(["gcloud", "storage", "cp", "--recursive", vm, "gs://{0}".format(config['bucket'])], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))

def start_import(vm):
    print("* starting import")
    result = subprocess.run(["gcloud", "compute", "instances", "import", vm, "--source-uri=gs://{0}/{1}".format(config['bucket'], vm), "--project", config['gcp_project'], "--network", config['gcp_vpc'], "--subnet", config['gcp_subnet'], "--zone", config['zone']], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))

def generate_vapp_template(vapp_name):
    print("* starting generation of vapp template for vapp {0}".format(vapp_name))
    # -i means "identical", which allows for capturing with no power off
    result = subprocess.run(["vcd", "vapp", "capture", "-i", vapp_name, config['catalog']], stdout=sys.stdout, stderr=subprocess.PIPE)
    if "already exists" in result.stderr.decode():
        print("template already exists, skipping")
        return
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))

def removedir(vm):
    result = subprocess.run(["rm", "{0}/*".format(vm)], stdout=sys.stdout, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise Exception("run failed, details:{0}".format(result))
    os.rmdir(vm)

def main():
    with open('config.yaml', 'r') as file:
        global config
        config = yaml.safe_load(file)
    vcd_login()
    for vm in config['vm_list']:
        print("--- processing VM {0}".format(vm))
        vapp_name = get_hidden_vapp_name(vm)
        generate_vapp_template(vapp_name)
        os.makedirs(vm)
        run_ovftool(vm, vapp_name)
        remove_ovf_collection(vm)
        upload_to_bucket(vm)
        removedir(vm)
        start_import(vm)
    return 0

if __name__ == '__main__':
    sys.exit(main())
