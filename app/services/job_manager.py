# /app/services/job_manager.py

class JobManager:
    def __init__(self):
        self.jobs = {}
        self.cancelled = set()  

    def add(self, job_id, process):
        self.jobs[job_id] = process

    def cancel(self, job_id):
        proc = self.jobs.pop(job_id, None)
        if proc and proc.poll() is None:
            proc.terminate()     # or kill if needed
        self.cancelled.add(job_id)
        return True if proc else False

    def get_status(self, job_id):
        if job_id in self.cancelled:
            return "cancelled"
        proc = self.jobs.get(job_id)
        if not proc:
            return "not_found"
        if proc.poll() is None:
            return "running"
        else:
            return "finished"

# instantiate globally
job_manager = JobManager()
