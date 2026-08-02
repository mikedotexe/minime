use astrid_minime_protocol::{CompatibilityStatus, EigenPacketV1, SensoryMsg, SensoryPacketV1};
use minime::owner_inquiry_wire::OwnerInquiryV1;
use minime::owner_inquiry_wire_v2::{canonical_owner_inquiry_sha256_v2, OwnerInquiryV2};
use sha2::{Digest as _, Sha256};

const OWNER_INQUIRY_FIXTURE_SHA256: &str =
    "f8645cd12c9a8c0f405e0d6dd7884feb497a2bad45f20ef55be052f040d01752";
const OWNER_INQUIRY_V2_FIXTURE_SHA256: &str =
    "17302b92b7d68eec9019ce7f2fb97731f22f4cba3c4ab53d762726cfd161e8c9";
const OWNER_INQUIRY_V2_CANONICAL_SHA256: &str =
    "55fb17ce4c29bdb3c24bb087788e7bef75442a2ab3ef3c53d933baaafcf10dc1";

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

#[test]
fn mirrored_owner_inquiry_fixture_round_trips_without_wire_drift() {
    let fixture = include_bytes!("fixtures/owner_inquiry_v1.json");
    assert_eq!(
        format!("{:x}", Sha256::digest(fixture)),
        OWNER_INQUIRY_FIXTURE_SHA256
    );
    let source: serde_json::Value = serde_json::from_slice(fixture).unwrap();
    let inquiry: OwnerInquiryV1 = serde_json::from_value(source.clone()).unwrap();

    assert_eq!(inquiry.strands.len(), 2);
    assert!(inquiry
        .strands
        .iter()
        .all(|strand| strand.projection_48d.len() == 48));
    assert_eq!(serde_json::to_value(inquiry).unwrap(), source);
}

#[test]
fn mirrored_owner_inquiry_v2_fixture_is_valid_and_byte_pinned() {
    let fixture = include_bytes!("fixtures/owner_inquiry_v2.json");
    assert_eq!(
        format!("{:x}", Sha256::digest(fixture)),
        OWNER_INQUIRY_V2_FIXTURE_SHA256
    );
    let source: serde_json::Value = serde_json::from_slice(fixture).unwrap();
    let inquiry: OwnerInquiryV2 = serde_json::from_value(source.clone()).unwrap();

    assert!(inquiry.is_well_formed());
    assert!(inquiry.preserve_all_strands_without_merge);
    assert_eq!(inquiry.analysis_plan.len(), 3);
    assert_eq!(
        canonical_owner_inquiry_sha256_v2(&inquiry),
        OWNER_INQUIRY_V2_CANONICAL_SHA256
    );
    assert_eq!(serde_json::to_value(inquiry).unwrap(), source);
}
