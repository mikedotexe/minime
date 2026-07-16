use astrid_minime_protocol::{CompatibilityStatus, EigenPacketV1, SensoryMsg, SensoryPacketV1};

#[test]
fn captured_legacy_and_current_telemetry_match_the_pinned_protocol() {
    let legacy: EigenPacketV1 =
        serde_json::from_str(include_str!("fixtures/legacy_eigenpacket.json")).unwrap();
    let current: EigenPacketV1 =
        serde_json::from_str(include_str!("fixtures/current_eigenpacket.json")).unwrap();

    assert_eq!(
        legacy.compatibility(),
        CompatibilityStatus::LegacyUnversioned
    );
    assert_eq!(current.compatibility(), CompatibilityStatus::Current);
    assert_eq!(
        current.extensions["future_additive_packet"]["preserved"],
        true
    );
}

#[test]
fn captured_control_fixture_includes_the_previously_drifted_fields() {
    let packet: SensoryPacketV1 =
        serde_json::from_str(include_str!("fixtures/sensory_control_all.json")).unwrap();

    match packet.message {
        SensoryMsg::Control {
            live_audio_enabled,
            live_video_enabled,
            pi_geom_weight,
            ..
        } => {
            assert_eq!(live_audio_enabled, Some(true));
            assert_eq!(live_video_enabled, Some(true));
            assert_eq!(pi_geom_weight, Some(0.7));
        }
        _ => panic!("expected control packet"),
    }
}
