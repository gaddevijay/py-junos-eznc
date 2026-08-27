from jnpr.junos.exception import RpcError


def provides_facts():
    """
    Returns a dictionary keyed on the facts provided by this module. The value
    of each key is the doc string describing the fact.
    """
    return {
        "jnu_satellite": "A boolean indicating if JNU satellite devices are "
        "present. False if none found or RPC not supported.",
        "satellites_info": "A dictionary keyed on satellite name. Each value "
        "is a dictionary of facts collected from that satellite, "
        "mirroring the same facts gathered for the main device: "
        "'alive', 'hostname', 'model', 'version', 'os_name', "
        "'serialnumber', '2RE', 'RE_hw_mi', 'RE0', 'RE1', "
        "'re_info', 're_master', 'master', 'vc_capable', "
        "'vc_mode', 'vc_fabric', 'vc_master'. Fields that "
        "cannot be determined are set to None.",
    }


def _get_sat_dev(rsp, name):
    """Return the <satellite-device> element matching *name*, or first found."""
    sat_dev = rsp.find(".//satellite-device[satellite-mgmt-ip='{}']".format(name))
    return sat_dev if sat_dev is not None else rsp.find(".//satellite-device")


def _collect_sw_facts(device, name, sat_facts):
    """Populate software version facts from get_software_information."""
    try:
        rsp = device.rpc.get_software_information(device_list=name, normalize=True)
        if rsp is None or rsp is True:
            return
        sat_dev = _get_sat_dev(rsp, name)
        if sat_dev is None:
            return
        sw = sat_dev.find(".//software-information")
        if sw is None:
            return
        sat_facts["hostname"] = sw.findtext("host-name")
        sat_facts["os_name"] = sw.findtext("os-name")
        sat_facts["model"] = sw.findtext("product-model") or sat_facts["model"]
        sat_facts["version"] = sw.findtext("junos-version") or sat_facts["version"]
    except Exception:
        pass


def _collect_re_facts(device, name, sat_facts):
    """Populate RE facts from get_route_engine_information."""
    try:
        rsp = device.rpc.get_route_engine_information(device_list=name, normalize=True)
        if rsp is None or rsp is True:
            return
        sat_dev = _get_sat_dev(rsp, name)
        if sat_dev is None:
            return
        re_list = sat_dev.findall(".//route-engine")
        sat_facts["2RE"] = len(re_list) > 1
        sat_facts["RE_hw_mi"] = False
        re_info_node = {"default": {}}
        first_slot = None
        master_slot = None
        for re in re_list:
            slot = re.findtext("slot", "0")
            info = {
                "mastership_state": re.findtext("mastership-state", "master"),
                "status": re.findtext("status"),
                "model": re.findtext("model"),
                "last_reboot_reason": re.findtext("last-reboot-reason"),
                "up_time": re.findtext("up-time"),
            }
            re_info_node[slot] = info
            if first_slot is None:
                first_slot = slot
                re_info_node["default"] = dict(info)
            if info["mastership_state"] == "master" and master_slot is None:
                master_slot = slot
            if slot == "0":
                sat_facts["RE0"] = dict(info)
            elif slot == "1":
                sat_facts["RE1"] = dict(info)
        sat_facts["re_info"] = {"default": re_info_node}
        sat_facts["re_master"] = {"default": master_slot or first_slot or "0"}
        sat_facts["master"] = "RE{}".format(master_slot or first_slot or "0")
    except Exception:
        pass


def _collect_chassis_facts(device, name, sat_facts):
    """Populate chassis inventory facts from get_chassis_inventory."""
    try:
        rsp = device.rpc.get_chassis_inventory(device_list=name, normalize=True)
        if rsp is None or rsp is True:
            return
        sat_dev = _get_sat_dev(rsp, name)
        if sat_dev is None:
            return
        sat_facts["serialnumber"] = sat_dev.findtext(
            ".//chassis[1]/serial-number"
        ) or sat_dev.findtext('.//chassis-module[name="Midplane"]/serial-number')
    except Exception:
        pass


def _collect_vc_facts(device, name, sat_facts):
    """Populate virtual chassis facts from get_virtual_chassis_information."""
    sat_facts["vc_capable"] = False
    sat_facts["vc_mode"] = None
    sat_facts["vc_fabric"] = None
    sat_facts["vc_master"] = None
    try:
        rsp = device.rpc.get_virtual_chassis_information(
            device_list=name, normalize=True
        )
        if rsp is None or rsp is True:
            return
        sat_dev = _get_sat_dev(rsp, name)
        if sat_dev is None:
            return
        # If the satellite returned an rpc-error (e.g. VC subsystem not running)
        # vc_capable remains False.
        if sat_dev.find(".//rpc-error") is not None:
            return
        vc_info = sat_dev.find(".//virtual-chassis-information")
        if vc_info is None:
            return
        sat_facts["vc_capable"] = True
        sat_facts["vc_mode"] = vc_info.findtext(".//virtual-chassis-mode")
        vc_id_info = vc_info.find(".//virtual-chassis-id-information")
        if vc_id_info is not None:
            sat_facts["vc_fabric"] = vc_id_info.get("style") == "fabric"
        for member_id in vc_info.xpath(
            ".//member-role[starts-with(.,'Master')]/preceding-sibling::member-id"
        ):
            if sat_facts["vc_master"] is None:
                sat_facts["vc_master"] = member_id.text
    except Exception:
        pass


def get_facts(device):
    """
    Gathers satellite device facts from the <get-jnu-satellites-information/>
    RPC, then for each live satellite collects the same facts as the main
    device via device-list RPCs:
      - software version  : get_software_information
      - RE information    : get_route_engine_information
      - chassis inventory : get_chassis_inventory
      - virtual chassis   : get_virtual_chassis_information
    """
    jnu_satellite = False
    satellites_info = {}

    try:
        rsp = device.rpc.get_jnu_satellites_information(normalize=True)
        if rsp is None or rsp is True:
            return {"jnu_satellite": jnu_satellite, "satellites_info": satellites_info}

        if rsp.tag == "error":
            raise RpcError()

        sat_list = rsp.findall(".//satellite-information")
        if not sat_list:
            return {"jnu_satellite": jnu_satellite, "satellites_info": satellites_info}

        jnu_satellite = True

        for sat in sat_list:
            name = sat.findtext("satellite-ip")
            if not name:
                continue

            alive = sat.findtext("alive")

            sat_facts = {
                "alive": alive,
                "model": sat.findtext("satellite-model"),
                "version": sat.findtext("satellite-version"),
                "hostname": None,
                "os_name": None,
                "serialnumber": None,
                "2RE": False,
                "RE_hw_mi": False,
                "RE0": None,
                "RE1": None,
                "re_info": None,
                "re_master": None,
                "master": None,
                "vc_capable": False,
                "vc_mode": None,
                "vc_fabric": None,
                "vc_master": None,
            }

            if alive == "up":
                _collect_sw_facts(device, name, sat_facts)
                _collect_re_facts(device, name, sat_facts)
                _collect_chassis_facts(device, name, sat_facts)
                _collect_vc_facts(device, name, sat_facts)

            satellites_info[name] = sat_facts

    except RpcError:
        # Device does not support JNU satellites RPC — not an error condition.
        pass
    except Exception:
        pass

    return {
        "jnu_satellite": jnu_satellite,
        "satellites_info": satellites_info,
    }
