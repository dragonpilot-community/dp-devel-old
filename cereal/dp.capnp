using Cxx = import "./include/c++.capnp";
$Cxx.namespace("cereal");

using Java = import "./include/java.capnp";
$Java.package("ai.comma.openpilot.cereal");
$Java.outerClassname("dp");

@0xbfa7e645486440c7;

# dp.capnp: a home for deprecated structs

# dp - legacy struct for apk
struct NavStatus {
  isNavigating @0 :Bool;
  currentAddress @1 :Address;

  struct Address {
    title @0 :Text;
    lat @1 :Float64;
    lng @2 :Float64;
    house @3 :Text;
    address @4 :Text;
    street @5 :Text;
    city @6 :Text;
    state @7 :Text;
    country @8 :Text;
  }
}

struct ThermalData {
  freeSpace @0 :Float32;
}

# dp
struct DragonConf {
  dpThermalStarted @0 :Bool;
  dpThermalOverheat @1 :Bool;
  dpVw @2 :Bool;
  dpAtl @3 :Bool;
  dpAppWaze @4 :Bool;
  dpAppWazeManual @5 :Int8;
  dpAppHr @6 :Bool;
  dpAppHrManual @7 :Int8;
  dpDashcam @8 :Bool;
  dpDashcamUi @9 :Bool;
  dpAutoShutdown @10 :Bool;
  dpAthenad @11 :Bool;
  dpUploader @12 :Bool;
  dpLatCtrl @13 :Bool;
  dpSteeringLimitAlert @14 :Bool;
  dpSteeringOnSignal @15 :Bool;
  dpSignalOffDelay @16 :UInt8;
  dpAssistedLcMinMph @17 :Float32;
  dpAutoLc @18 :Bool;
  dpAutoLcCont @19 :Bool;
  dpAutoLcMinMph @20 :Float32;
  dpAutoLcDelay @21 :Float32;
  dpSlowOnCurve @22 :Bool;
  dpAllowGas @23 :Bool;
  dpMaxCtrlSpeed @24 :Float32;
  dpLeadCarAlert @25 :Bool;
  dpDynamicFollow @26 :UInt8;
  dpAccelProfile @27 :UInt8;
  dpDriverMonitor @28 :Bool;
  dpSteeringMonitor @29 :Bool;
  dpSteeringMonitorTimer @30 :UInt8;
  dpGearCheck @31 :Bool;
  dpDrivingUi @32 :Bool;
  dpUiScreenOffReversing @33 :Bool;
  dpUiScreenOffDriving @34 :Bool;
  dpUiSpeed @35 :Bool;
  dpUiEvent @36 :Bool;
  dpUiMaxSpeed @37 :Bool;
  dpUiFace @38 :Bool;
  dpUiLane @39 :Bool;
  dpUiPath @40 :Bool;
  dpUiLead @41 :Bool;
  dpUiDev @42 :Bool;
  dpUiDevMini @43 :Bool;
  dpUiBlinker @44 :Bool;
  dpUiBrightness @45 :UInt8;
  dpUiVolumeBoost @46 :Int8;
  dpAppAutoUpdate @47 :Bool;
  dpAppExtGps @48 :Bool;
  dpAppTomtom @49 :Bool;
  dpAppTomtomAuto @50 :Bool;
  dpAppTomtomManual @51 :Int8;
  dpAppAutonavi @52 :Bool;
  dpAppAutonaviAuto @53 :Bool;
  dpAppAutonaviManual @54 :Int8;
  dpAppAegis @55 :Bool;
  dpAppAegisAuto @56 :Bool;
  dpAppAegisManual @57 :Int8;
  dpAppMixplorer @58 :Bool;
  dpAppMixplorerManual @59 :Int8;
  dpCarDetected @60 :Text;
  dpToyotaLdw @61 :Bool;
  dpToyotaSng @62 :Bool;
  dpToyotaLowestCruiseOverride @63 :Bool;
  dpToyotaLowestCruiseOverrideVego @64 :Bool;
  dpToyotaLowestCruiseOverrideAt @65 :Float32;
  dpToyotaLowestCruiseOverrideSpeed @66 :Float32;
  dpIpAddr @67 :Text;
  dpCameraOffset @68 :Int8;
  dpLocale @69 :Text;
  dpChargingCtrl @70 :Bool;
  dpChargingAt @71 :UInt8;
  dpDischargingAt @72 :UInt8;
  dpIsUpdating @73 :Bool;
  dpTimebombAssist @74 :Bool;
}