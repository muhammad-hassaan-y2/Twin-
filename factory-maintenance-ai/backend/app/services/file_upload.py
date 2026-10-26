import os
import uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.config import settings


class FileUploadService:
    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = settings.MAX_FILE_SIZE
        self.allowed_extensions = set(settings.ALLOWED_EXTENSIONS.split(","))
    
    def validate_file(self, file: UploadFile) -> None:
        """Validate uploaded file."""
        # Check file extension
        ext = file.filename.split(".")[-1].lower() if file.filename else ""
        if ext not in self.allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(self.allowed_extensions)}"
            )
        
        # Check file size (read first chunk to estimate)
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        if size > self.max_file_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {self.max_file_size / (1024*1024):.1f}MB"
            )
    
    async def save_file(self, file: UploadFile, prefix: str = "") -> str:
        """Save uploaded file and return path."""
        self.validate_file(file)
        
        # Generate unique filename
        ext = file.filename.split(".")[-1].lower() if file.filename else "jpg"
        unique_name = f"{prefix}{uuid.uuid4().hex}.{ext}"
        file_path = self.upload_dir / unique_name
        
        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        return str(file_path)
    
    def delete_file(self, file_path: str) -> bool:
        """Delete file if it exists."""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                return True
        except Exception:
            pass
        return False
    
    def get_file_url(self, file_path: str) -> str:
        """Get URL for accessing the file (for frontend)."""
        if not file_path:
            return None
        filename = Path(file_path).name
        return f"/api/files/{filename}"


file_upload_service = FileUploadService()