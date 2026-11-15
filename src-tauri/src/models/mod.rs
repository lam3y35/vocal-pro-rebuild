use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;

use crate::error::AppResult;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub stems: Vec<String>,
    pub relative_compute: f32,
    pub cached: bool,
}

pub fn list_supported_models(torch_hub_checkpoints_dir: Option<&Path>) -> Vec<ModelInfo> {
    match torch_hub_checkpoints_dir {
        Some(dir) => list_supported_models_in_dirs(&[dir]),
        None => list_supported_models_in_dirs(&[]),
    }
}

type ModelDef<'a> = (&'a str, &'a str, &'a str, Vec<&'a str>, f32, &'a [&'a str]);

pub fn list_supported_models_in_dirs(search_dirs: &[&Path]) -> Vec<ModelInfo> {
    let defs: [ModelDef<'_>; 8] = [
        (
            "htdemucs",
            "HTDemucs (Fast & Balanced)",
            "Hybrid Transformer Demucs v4 — default balanced 4-stem model.",
            vec!["vocals", "drums", "bass", "other"],
            1.0_f32,
            &["955717e8-8726e21a.th"],
        ),
        (
            "htdemucs_ft",
            "HTDemucs Fine-Tuned (Best Vocal Quality)",
            "Bag of 4 specialist fine-tuned Hybrid Transformer models (~4x compute, highest vocal SDR).",
            vec!["vocals", "drums", "bass", "other"],
            4.0_f32,
            &[
                "f7e0c4bc-ba3fe64a.th",
                "d12395a8-e57c48e6.th",
                "92cfc3b6-ef3bcb9c.th",
                "04573f0d-f3cf25b2.th",
            ],
        ),
        (
            "htdemucs_6s",
            "HTDemucs 6-Stem (Full Band)",
            "6-stem separation: vocals, drums, bass, guitar, piano, and other.",
            vec!["vocals", "drums", "bass", "guitar", "piano", "other"],
            1.2_f32,
            &["5c90dfd2-34c22ccb.th"],
        ),
        (
            "hdemucs_mmi",
            "HDemucs MMI",
            "Hybrid Demucs v3 trained on MUSDB + extra MMI dataset.",
            vec!["vocals", "drums", "bass", "other"],
            1.0_f32,
            &["75fc33f5-1941ce65.th"],
        ),
        (
            "mdx",
            "MDX-Net",
            "MDX-Challenge Hybrid Demucs model.",
            vec!["vocals", "drums", "bass", "other"],
            1.5_f32,
            &[
                "0d19c1c6-0f06f20e.th",
                "7ecf8ec1-70f50cc9.th",
                "c511e2ab-fe698775.th",
                "7d865c68-3d5dd56b.th",
            ],
        ),
        (
            "mdx_extra",
            "MDX-Net Extra",
            "MDX-Net trained with extra data (used in Ensemble Mode alongside htdemucs_ft).",
            vec!["vocals", "drums", "bass", "other"],
            2.0_f32,
            &[
                "e51eebcc-c1b80bdd.th",
                "a1d90b5c-ae9d2452.th",
                "5d2d6c55-db83574e.th",
                "cfa93e08-61801ae1.th",
            ],
        ),
        (
            "mdx_q",
            "MDX-Net Quantized (Lightweight)",
            "Quantized MDX model with smaller disk/memory footprint.",
            vec!["vocals", "drums", "bass", "other"],
            1.1_f32,
            &[
                "6b9c2ca1-3fd82607.th",
                "b72baf4e-8778635e.th",
                "42e558d4-196e0e1b.th",
                "305bc58f-18378783.th",
            ],
        ),
        (
            "mdx_extra_q",
            "MDX-Net Extra Quantized",
            "Quantized MDX-Extra model.",
            vec!["vocals", "drums", "bass", "other"],
            1.3_f32,
            &[
                "83fc094f-4a16d450.th",
                "464b36d7-e5a9386e.th",
                "14fc6a69-a89dd0ee.th",
                "7fd6ef75-a905dd85.th",
            ],
        ),
    ];

    defs.into_iter()
        .map(|(id, name, desc, stems, compute, weight_files)| {
            let cached = weight_files
                .iter()
                .all(|wf| search_dirs.iter().any(|dir| dir.join(wf).is_file()));
            ModelInfo {
                id: id.to_string(),
                display_name: name.to_string(),
                description: desc.to_string(),
                stems: stems.into_iter().map(|s| s.to_string()).collect(),
                relative_compute: compute,
                cached,
            }
        })
        .collect()
}

pub fn compute_file_sha256(path: &Path) -> AppResult<String> {
    let bytes = std::fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(hex::encode(hasher.finalize()))
}
