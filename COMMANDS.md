# Quick Command Reference

1. Generate and save Shorts
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID"
```

2. Generate and upload Shorts
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --auto-upload
```

3. Upload next pending Short
```powershell
python upload_pending.py
```

4. Upload all pending Shorts
```powershell
python cli.py --upload-all-pending
```

5. Authorize YouTube channel OAuth
```powershell
python cli.py --auth-youtube
```

6. Run system health check
```powershell
python cli.py --doctor
```

7. Purge cache and space
```powershell
python cli.py --clean-cache
```

8. Save raw source files
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --keep-raw
```

9. Extract specific clip count
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --clips-count 5
```

10. Use face tracking crop
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --crop-mode face_tracking
```

11. Run automated unit tests
```powershell
pytest tests/test_pipeline_units.py -v
```

12. Extract Shorts without captions
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --no-captions
```

13. Extract continuous uncut Shorts
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --single-clip
```

14. Extract clean stream Shorts
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --stream-mode
```

15. Disable swear word bleeping
```powershell
python cli.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --no-bleep-profanity
```
