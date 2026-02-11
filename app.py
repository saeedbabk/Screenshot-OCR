"""
Screenshot OCR v2.0 — Flask Application
Single entry point: python app.py
"""
import os
import sys
import json
import time
import uuid
import shutil
import threading
import subprocess
import webbrowser
from queue import Queue
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_file

import config
import database

app = Flask(__name__)

# ========================================
# Job Management
# ========================================

# In-memory job tracker
jobs = {}  # job_id -> {status, results, progress_queue, ...}

def create_job(input_folder, output_folder):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'id': job_id,
        'status': 'running',
        'input_folder': input_folder,
        'output_folder': output_folder,
        'results': None,
        'error': None,
        'progress_queue': Queue(),
        'start_time': time.time(),
        'failures': []
    }
    return job_id

# ========================================
# Browse Dialog (embedded, subprocess-safe)
# ========================================

def open_folder_dialog():
    dialog_script = """
import tkinter as tk
from tkinter import filedialog
try:
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askdirectory()
    if path:
        print(path)
    root.destroy()
except:
    pass
"""
    try:
        result = subprocess.check_output(
            [sys.executable, '-c', dialog_script],
            encoding='utf-8', timeout=120
        )
        return result.strip()
    except Exception as e:
        print(f"Dialog error: {e}")
        return ""

# ========================================
# Routes — Pages
# ========================================

@app.route('/')
def index():
    return render_template('index.html')

# ========================================
# Routes — Browse
# ========================================

@app.route('/browse', methods=['GET'])
def browse():
    path = open_folder_dialog()
    if path:
        path = os.path.abspath(path).replace('\\', '/')
        return jsonify({'path': path})
    return jsonify({'path': ''})

# ========================================
# Routes — Processing
# ========================================

@app.route('/start', methods=['POST'])
def start():
    data = request.json
    input_folder = data.get('input_folder')
    output_folder = data.get('output_folder')

    if not input_folder or not output_folder:
        return jsonify({'error': 'Please select both input and output folders.'}), 400

    if not os.path.exists(input_folder):
        return jsonify({'error': 'Input folder does not exist.'}), 400

    job_id = create_job(input_folder, output_folder)

    # Run processing in background thread
    thread = threading.Thread(target=run_processing, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({'job_id': job_id})

def run_processing(job_id):
    """Background processing thread — delegates to OCR engine with progress callback."""
    job = jobs[job_id]

    try:
        import screenshot_timestamp_reader as ocr

        cfg = config.load()
        workers = cfg.get('parallel_workers', 1)
        naming = cfg.get('naming_template', '')

        # Progress callback — pushes events to the SSE queue
        def on_progress(data):
            job['progress_queue'].put({
                'type': 'progress',
                **data
            })
            # Track failures for database
            if data.get('status') == 'failed':
                job['failures'].append({
                    'filename': data.get('filename', ''),
                    'input_path': '',  # filled from results
                    'ocr_text': data.get('message', '')[:200]
                })

        # Run the OCR engine
        results = ocr.process_images(
            job['input_folder'], job['output_folder'],
            progress_callback=on_progress,
            workers=workers,
            naming_template=naming
        )

        # Calculate duration
        elapsed = time.time() - job['start_time']
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        duration = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        job['status'] = 'complete'
        job['results'] = results

        # Record to database
        db_job_id = database.record_job(
            job['input_folder'], job['output_folder'],
            results['total'], results['success'], results['failed'],
            duration, results.get('log_file', '')
        )

        # Record failures from OCR engine results
        for f in results.get('failures', []):
            database.record_failure(db_job_id, f['filename'], f['input_path'], f.get('ocr_text', ''))

        job['progress_queue'].put({'type': 'complete', 'results': results})

    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)
        job['progress_queue'].put({'type': 'error', 'message': str(e)})
        import traceback
        traceback.print_exc()


def ocr_sanitize(text):
    """Make text safe for filenames."""
    return text.replace(':', '_').replace('/', '_').replace('\\', '_')

# ========================================
# Routes — SSE Stream
# ========================================

@app.route('/stream')
def stream():
    job_id = request.args.get('job_id')
    if not job_id or job_id not in jobs:
        return jsonify({'error': 'Invalid job ID'}), 404

    def event_stream():
        job = jobs[job_id]
        while True:
            try:
                msg = job['progress_queue'].get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg['type'] in ('complete', 'error'):
                    break
            except Exception:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                if job['status'] in ('complete', 'error'):
                    break

    return Response(event_stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ========================================
# Routes — Job Status (polling fallback)
# ========================================

@app.route('/job/<job_id>/status')
def job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404

    job = jobs[job_id]
    return jsonify({
        'status': job['status'],
        'results': job['results'],
        'message': job.get('error', '')
    })

# ========================================
# Routes — Settings API
# ========================================

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(config.load())

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    cfg = config.load()
    cfg.update(data)
    config.save(cfg)
    return jsonify({'status': 'ok'})

# ========================================
# Routes — History API
# ========================================

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(database.get_history())

@app.route('/api/history/<int:job_id>', methods=['DELETE'])
def delete_history(job_id):
    database.delete_job(job_id)
    return jsonify({'status': 'ok'})

# ========================================
# Routes — Failures API
# ========================================

@app.route('/api/failures', methods=['GET'])
def get_failures():
    job_id = request.args.get('job_id')
    failures = database.get_failures(int(job_id) if job_id else None)
    return jsonify(failures)

@app.route('/api/override', methods=['POST'])
def override_timestamp():
    data = request.json
    filename = data.get('filename')
    timestamp = data.get('timestamp')

    if not filename or not timestamp:
        return jsonify({'error': 'Missing filename or timestamp'}), 400

    failure = database.get_failure_by_filename(filename)
    if not failure:
        return jsonify({'error': 'Failure record not found'}), 404

    try:
        input_path = Path(failure['input_path'])
        if not input_path.exists():
            return jsonify({'error': 'Source file no longer exists'}), 404

        # Find the most recent job's output folder
        history = database.get_history(limit=1)
        if not history:
            return jsonify({'error': 'No output folder found in history'}), 400

        output_path = Path(history[0]['output_path'])
        safe_name = ocr_sanitize(timestamp) + input_path.suffix
        new_path = output_path / safe_name

        counter = 1
        while new_path.exists():
            safe_name = f"{ocr_sanitize(timestamp)}_{counter}{input_path.suffix}"
            new_path = output_path / safe_name
            counter += 1

        shutil.copy2(input_path, new_path)
        database.resolve_failure(failure['id'])

        return jsonify({'status': 'ok', 'new_filename': safe_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/retry', methods=['POST'])
def retry_image():
    data = request.json
    filename = data.get('filename')

    failure = database.get_failure_by_filename(filename)
    if not failure:
        return jsonify({'error': 'Failure not found'}), 404

    input_path = failure['input_path']
    if not os.path.exists(input_path):
        return jsonify({'error': 'Source file not found'}), 404

    try:
        import screenshot_timestamp_reader as ocr
        timestamp, raw_text = ocr.read_timestamp_from_image(input_path)

        if timestamp:
            history = database.get_history(limit=1)
            if history:
                output_path = Path(history[0]['output_path'])
                safe_name = ocr_sanitize(timestamp) + Path(input_path).suffix
                new_path = output_path / safe_name

                counter = 1
                while new_path.exists():
                    safe_name = f"{ocr_sanitize(timestamp)}_{counter}{Path(input_path).suffix}"
                    new_path = output_path / safe_name
                    counter += 1

                shutil.copy2(input_path, new_path)

            database.resolve_failure(failure['id'])
            return jsonify({'success': True, 'timestamp': timestamp})
        else:
            return jsonify({'success': False, 'ocr_text': raw_text[:200]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========================================
# Entry Point
# ========================================

if __name__ == '__main__':
    print("=" * 50)
    print("  Screenshot OCR v2.0")
    print("  http://127.0.0.1:5000")
    print("=" * 50)

    # Auto-open browser after a short delay
    def open_browser():
        time.sleep(1.2)
        webbrowser.open('http://127.0.0.1:5000')

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(debug=True, use_reloader=False, threaded=True)
