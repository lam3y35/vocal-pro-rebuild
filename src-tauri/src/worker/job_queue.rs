use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};

use crate::worker::protocol::{JobOptions, StemOutput};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Queued,
    LoadingModel,
    Decoding,
    Inferring,
    PostProcessing,
    Writing,
    Done,
    Cancelled,
    Failed,
}

impl JobStatus {
    pub fn from_worker_phase(phase: &str) -> Self {
        match phase {
            "loading_model" => Self::LoadingModel,
            "decoding" => Self::Decoding,
            "inference" => Self::Inferring,
            "postprocess_sfx"
            | "postprocess_denoise"
            | "postprocess_gate"
            | "postprocess_eq"
            | "postprocess_normalize" => Self::PostProcessing,
            "writing" | "muxing_video" => Self::Writing,
            _ => Self::Inferring,
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Done | Self::Cancelled | Self::Failed)
    }
}

fn default_priority() -> String {
    "normal".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobRecord {
    pub job_id: String,
    pub input_path: String,
    pub output_dir: String,
    pub options: JobOptions,
    pub status: JobStatus,
    pub phase: String,
    pub percent: f64,
    pub segment_index: u32,
    pub segment_total: u32,
    pub sub_model_index: u32,
    pub sub_model_total: u32,
    pub eta_s: Option<f64>,
    pub message: String,
    pub stems: Vec<StemOutput>,
    pub comparison_samples: Vec<String>,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
    pub created_at: String,
    pub elapsed_s: Option<f64>,
    #[serde(default)]
    pub worker_slot: Option<u32>,
    #[serde(default = "default_priority")]
    pub priority: String,
}

#[derive(Default)]
pub struct JobQueue {
    jobs: HashMap<String, JobRecord>,
    order: Vec<String>,
    waiting: HashSet<String>,
}

impl JobQueue {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn enqueue(
        &mut self,
        job_id: String,
        input_path: String,
        output_dir: String,
        options: JobOptions,
    ) -> JobRecord {
        self.enqueue_with_priority(
            job_id,
            input_path,
            output_dir,
            options,
            "normal".to_string(),
        )
    }

    pub fn enqueue_with_priority(
        &mut self,
        job_id: String,
        input_path: String,
        output_dir: String,
        options: JobOptions,
        priority: String,
    ) -> JobRecord {
        let now = chrono::Utc::now().to_rfc3339();
        let rec = JobRecord {
            job_id: job_id.clone(),
            input_path,
            output_dir,
            options,
            status: JobStatus::Queued,
            phase: "queued".to_string(),
            percent: 0.0,
            segment_index: 0,
            segment_total: 1,
            sub_model_index: 0,
            sub_model_total: 1,
            eta_s: None,
            message: "Queued".to_string(),
            stems: Vec::new(),
            comparison_samples: Vec::new(),
            error_code: None,
            error_message: None,
            created_at: now,
            elapsed_s: None,
            worker_slot: None,
            priority,
        };
        if !self.jobs.contains_key(&job_id) {
            self.order.push(job_id.clone());
        }
        self.waiting.insert(job_id.clone());
        self.jobs.insert(job_id, rec.clone());
        rec
    }

    pub fn mark_waiting(&mut self, job_id: &str) {
        if self.jobs.contains_key(job_id) {
            self.waiting.insert(job_id.to_string());
        }
    }

    pub fn restore_records(&mut self, records: Vec<JobRecord>) {
        for mut rec in records {
            if !rec.status.is_terminal() {
                rec.status = JobStatus::Failed;
                rec.phase = "failed".to_string();
                rec.eta_s = None;
                rec.error_code = Some("INTERRUPTED".to_string());
                rec.error_message = Some(
                    "Session interrupted before job completion. Click Retry to resume.".to_string(),
                );
                rec.message = "Interrupted on previous shutdown — ready to retry".to_string();
            }
            if !self.jobs.contains_key(&rec.job_id) {
                self.order.push(rec.job_id.clone());
            }
            self.jobs.insert(rec.job_id.clone(), rec);
        }
    }

    pub fn set_priority(&mut self, job_id: &str, priority: &str) -> Option<JobRecord> {
        let rec = self.jobs.get_mut(job_id)?;
        rec.priority = priority.to_lowercase();
        let updated = rec.clone();
        self.sort_queued_by_priority();
        Some(updated)
    }

    pub fn reorder(&mut self, job_id: &str, new_index: usize) -> bool {
        let Some(pos) = self.order.iter().position(|id| id == job_id) else {
            return false;
        };
        let id = self.order.remove(pos);
        let clamped = new_index.min(self.order.len());
        self.order.insert(clamped, id);
        true
    }

    fn sort_queued_by_priority(&mut self) {
        let rank = |p: &str| match p {
            "high" => 0,
            "normal" => 1,
            "low" => 2,
            _ => 1,
        };
        let jobs_ref = &self.jobs;
        self.order.sort_by_key(|id| {
            jobs_ref
                .get(id)
                .map(|r| rank(r.priority.as_str()))
                .unwrap_or(1)
        });
    }

    pub fn assign_slot(&mut self, job_id: &str, slot_id: u32) {
        self.waiting.remove(job_id);
        if let Some(rec) = self.jobs.get_mut(job_id) {
            rec.worker_slot = Some(slot_id);
        }
    }

    pub fn is_next_queued(&self, job_id: &str) -> bool {
        self.order
            .iter()
            .filter_map(|id| self.jobs.get(id))
            .find(|r| {
                r.status == JobStatus::Queued
                    && r.worker_slot.is_none()
                    && self.waiting.contains(&r.job_id)
            })
            .map(|r| r.job_id == job_id)
            .unwrap_or(true)
    }

    pub fn update_progress(
        &mut self,
        job_id: &str,
        phase: &str,
        segment_index: u32,
        segment_total: u32,
        sub_model_index: u32,
        sub_model_total: u32,
        percent: f64,
        eta_s: Option<f64>,
        message: Option<String>,
    ) -> Option<JobRecord> {
        let rec = self.jobs.get_mut(job_id)?;
        if rec.status.is_terminal() {
            return Some(rec.clone());
        }
        rec.status = JobStatus::from_worker_phase(phase);
        rec.phase = phase.to_string();
        rec.segment_index = segment_index;
        rec.segment_total = segment_total.max(1);
        rec.sub_model_index = sub_model_index;
        rec.sub_model_total = sub_model_total.max(1);
        rec.percent = percent.clamp(0.0, 100.0);
        rec.eta_s = eta_s;
        if let Some(m) = message {
            if !m.is_empty() {
                rec.message = m;
            }
        }
        Some(rec.clone())
    }

    pub fn mark_done(
        &mut self,
        job_id: &str,
        output_dir: String,
        stems: Vec<StemOutput>,
        comparison_samples: Vec<String>,
        elapsed_s: f64,
    ) -> Option<JobRecord> {
        self.waiting.remove(job_id);
        let rec = self.jobs.get_mut(job_id)?;
        rec.status = JobStatus::Done;
        rec.phase = "done".to_string();
        rec.percent = 100.0;
        rec.eta_s = Some(0.0);
        rec.output_dir = output_dir;
        rec.stems = stems;
        rec.comparison_samples = comparison_samples;
        rec.elapsed_s = Some(elapsed_s);
        rec.message = "Completed".to_string();
        Some(rec.clone())
    }

    pub fn mark_cancelled(&mut self, job_id: &str) -> Option<JobRecord> {
        self.waiting.remove(job_id);
        let rec = self.jobs.get_mut(job_id)?;
        if rec.status.is_terminal() {
            return Some(rec.clone());
        }
        rec.status = JobStatus::Cancelled;
        rec.phase = "cancelled".to_string();
        rec.message = "Cancelled by user".to_string();
        Some(rec.clone())
    }

    pub fn mark_failed(
        &mut self,
        job_id: &str,
        code: String,
        message: String,
    ) -> Option<JobRecord> {
        self.waiting.remove(job_id);
        let rec = self.jobs.get_mut(job_id)?;
        rec.status = JobStatus::Failed;
        rec.phase = "failed".to_string();
        rec.error_code = Some(code);
        rec.error_message = Some(message.clone());
        rec.message = message;
        Some(rec.clone())
    }

    pub fn get(&self, job_id: &str) -> Option<&JobRecord> {
        self.jobs.get(job_id)
    }

    pub fn list(&self) -> Vec<JobRecord> {
        self.order
            .iter()
            .filter_map(|id| self.jobs.get(id).cloned())
            .collect()
    }
}
