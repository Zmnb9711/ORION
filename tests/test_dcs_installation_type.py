from orion.dcs_installations import DcsInstallationCreate, DcsInstallationType, DcsInstallationUpdate


def test_user_can_explicitly_select_steam_installation():
    item = DcsInstallationCreate(
        name="DCS Steam",
        executable_path=r"C:\Program Files (x86)\Steam\steamapps\common\DCSWorld\bin\DCS.exe",
        installation_type=DcsInstallationType.STEAM,
    )
    assert item.installation_type == DcsInstallationType.STEAM


def test_user_can_explicitly_select_standalone_installation():
    item = DcsInstallationCreate(
        name="DCS Standalone",
        executable_path=r"C:\Program Files\Eagle Dynamics\DCS World\bin\DCS.exe",
        installation_type=DcsInstallationType.STANDALONE,
    )
    assert item.installation_type == DcsInstallationType.STANDALONE


def test_auto_and_manual_modes_remain_available():
    automatic = DcsInstallationCreate(name="Detected DCS", executable_path=r"D:\DCS\bin\DCS.exe")
    manual = DcsInstallationUpdate(installation_type=DcsInstallationType.MANUAL)
    assert automatic.installation_type == DcsInstallationType.AUTO
    assert manual.installation_type == DcsInstallationType.MANUAL


def test_saved_games_path_can_be_configured_separately():
    item = DcsInstallationCreate(
        name="DCS Steam",
        executable_path=r"D:\SteamLibrary\steamapps\common\DCSWorld\bin\DCS.exe",
        installation_type="steam",
        saved_games_path=r"C:\Users\Pilot\Saved Games\DCS",
    )
    assert item.saved_games_path.endswith(r"Saved Games\DCS")
