def _get_sat_dev(rsp, name):
    """Return the <satellite-device> element matching *name*, or first found."""
    sat_dev = rsp.find(".//satellite-device[satellite-mgmt-ip='{}']".format(name))
    return sat_dev if sat_dev is not None else rsp.find(".//satellite-device")


def facts_satellites(junos, facts):
    """
    Collects JNU satellite device facts, mirroring the same facts gathered
    for the main device via device-list RPCs:
      - software version  : get_software_information
      - RE information    : get_route_engine_information
      - chassis inventory : get_chassis_inventory
      - virtual chassis   : get_virtual_chassis_information

    The following facts are assigned:
        facts['jnu_satellite']  : True if satellite devices are present,
                                  False otherwise.
        facts['satellites_info']: A dict keyed by satellite name. Each value
                                  is a dict with keys: 'alive', 'hostname',
                                  'model', 'version', 'os_name',
                                  'serialnumber', '2RE', 'RE_hw_mi',
                                  'RE0', 'RE1', 're_info', 're_master',
                                  'master', 'vc_capable', 'vc_mode',
                                  'vc_fabric', 'vc_master'.
    """
    facts["jnu_satellite"] = False
    facts["satellites_info"] = {}

    try:
        rsp = junos.rpc.get_jnu_satellites_information()
        if rsp is None or rsp is True:
            return

        sat_list = rsp.findall(".//satellite-information")
        if not sat_list:
            return

        facts["jnu_satellite"] = True

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
                # --- software version facts ---
                try:
                    sw_rsp = junos.rpc.get_software_information(device_list=name)
                    if sw_rsp is not None and sw_rsp is not True:
                        sat_dev = _get_sat_dev(sw_rsp, name)
                        if sat_dev is not None:
                            sw = sat_dev.find(".//software-information")
                            if sw is not None:
                                sat_facts["hostname"] = sw.findtext("host-name")
                                sat_facts["os_name"] = sw.findtext("os-name")
                                sat_facts["model"] = (
                                    sw.findtext("product-model") or sat_facts["model"]
                                )
                                sat_facts["version"] = (
                                    sw.findtext("junos-version") or sat_facts["version"]
                                )
                except Exception:
                    pass

                # --- RE facts ---
                try:
                    re_rsp = junos.rpc.get_route_engine_information(device_list=name)
                    if re_rsp is not None and re_rsp is not True:
                        sat_dev = _get_sat_dev(re_rsp, name)
                        if sat_dev is not None:
                            re_list = sat_dev.findall(".//route-engine")
                            sat_facts["2RE"] = len(re_list) > 1
                            re_info_node = {"default": {}}
                            first_slot = None
                            master_slot = None
                            for re in re_list:
                                slot = re.findtext("slot", "0")
                                info = {
                                    "mastership_state": re.findtext(
                                        "mastership-state", "master"
                                    ),
                                    "status": re.findtext("status"),
                                    "model": re.findtext("model"),
                                    "last_reboot_reason": re.findtext(
                                        "last-reboot-reason"
                                    ),
                                    "up_time": re.findtext("up-time"),
                                }
                                re_info_node[slot] = info
                                if first_slot is None:
                                    first_slot = slot
                                    re_info_node["default"] = dict(info)
                                if (
                                    info["mastership_state"] == "master"
                                    and master_slot is None
                                ):
                                    master_slot = slot
                                if slot == "0":
                                    sat_facts["RE0"] = dict(info)
                                elif slot == "1":
                                    sat_facts["RE1"] = dict(info)
                            sat_facts["re_info"] = {"default": re_info_node}
                            sat_facts["re_master"] = {
                                "default": master_slot or first_slot or "0"
                            }
                            sat_facts["master"] = "RE{}".format(
                                master_slot or first_slot or "0"
                            )
                except Exception:
                    pass

                # --- chassis inventory facts ---
                try:
                    inv_rsp = junos.rpc.get_chassis_inventory(device_list=name)
                    if inv_rsp is not None and inv_rsp is not True:
                        sat_dev = _get_sat_dev(inv_rsp, name)
                        if sat_dev is not None:
                            sat_facts["serialnumber"] = sat_dev.findtext(
                                ".//chassis[1]/serial-number"
                            ) or sat_dev.findtext(
                                './/chassis-module[name="Midplane"]/serial-number'
                            )
                except Exception:
                    pass

                # --- virtual chassis facts ---
                try:
                    vc_rsp = junos.rpc.get_virtual_chassis_information(device_list=name)
                    if vc_rsp is not None and vc_rsp is not True:
                        sat_dev = _get_sat_dev(vc_rsp, name)
                        if sat_dev is not None and sat_dev.find(".//rpc-error") is None:
                            vc_info = sat_dev.find(".//virtual-chassis-information")
                            if vc_info is not None:
                                sat_facts["vc_capable"] = True
                                sat_facts["vc_mode"] = vc_info.findtext(
                                    ".//virtual-chassis-mode"
                                )
                                vc_id_info = vc_info.find(
                                    ".//virtual-chassis-id-information"
                                )
                                if vc_id_info is not None:
                                    sat_facts["vc_fabric"] = (
                                        vc_id_info.get("style") == "fabric"
                                    )
                                for member_id in vc_info.xpath(
                                    ".//member-role[starts-with(.,'Master')]"
                                    "/preceding-sibling::member-id"
                                ):
                                    if sat_facts["vc_master"] is None:
                                        sat_facts["vc_master"] = member_id.text
                except Exception:
                    pass

            facts["satellites_info"][name] = sat_facts

    except Exception:
        pass
