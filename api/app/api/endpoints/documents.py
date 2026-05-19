"""
FastAPI endpoints for document upload and processing with MD5 deduplication.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
import tempfile
import os

from app.db.database import get_db, async_session_maker
from app.crud.document import (
    calculate_md5_hash,
    get_document_by_md5,
    create_document,
    get_or_create_user,
    update_document_status,
    get_user_progress_for_document,
    create_progress
)
from app.services.document_processor import process_uploaded_document, DocumentProcessor
from app.core.chroma import create_document_collection, add_document_chunks
from app.core.security import get_current_user
from app.core.constants import MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB
from app.core.logging_config import get_logger
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    ChapterResponse,
    ProgressCreate
)
from app.models.document import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


# For demo: use a default user
DEFAULT_USER_EMAIL = "demo@edugenius.ai"
DEFAULT_USERNAME = "demo_user"


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload document with MD5-based deduplication and RAG processing.

    瀹屾暣娴佺▼锛?
    1. 璁＄畻 MD5 鍝堝笇
    2. 妫€鏌ユ槸鍚﹀凡瀛樺湪锛堝幓閲嶏級
    3. 瑙ｆ瀽 PDF/TXT
    4. 璇箟鍒囧垎
    5. DashScope 鍚戦噺鍖?
    6. 瀛樺叆 ChromaDB
    7. 鍒涘缓鏁版嵁搴撹褰?

    娉ㄦ剰锛氬ぇ鏂囦欢澶勭悊鍙兘闇€瑕佽緝闀挎椂闂达紝璇疯€愬績绛夊緟
    """
    import asyncio
    from app.core.config import settings

    # 鏂囦欢澶у皬闄愬埗锛?0MB锛?
    MAX_FILE_SIZE = 50 * 1024 * 1024

    # 璇诲彇鏂囦欢鍐呭
    content = await file.read()

    # 妫€鏌ユ枃浠跺ぇ灏?
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"鏂囦欢杩囧ぇ锛屾渶澶ф敮鎸?{MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # 淇濆瓨鍒颁复鏃舵枃浠?
    tmp_file_path = None
    permanent_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()  # 馃敡 纭繚鍐呭鍐欏叆纾佺洏
            tmp_file_path = tmp_file.name

        print(f"馃搫 寮€濮嬪鐞嗘枃妗? {file.filename} ({len(content)} bytes)")

        # 璁＄畻鏂囨。澶勭悊鍣?
        processor = DocumentProcessor()
        md5_hash = processor.calculate_md5(tmp_file_path)
        print(f"馃攼 MD5: {md5_hash}")

        # 妫€鏌ユ槸鍚﹀凡瀛樺湪
        existing_document = await get_document_by_md5(db, md5_hash)

        if existing_document:
            # md5_hash is globally unique. Reuse the existing document and
            # create this user's learning progress rows when needed.
            from sqlalchemy import select
            from app.models.document import Progress

            progress_result = await db.execute(
                select(Progress).where(
                    Progress.user_id == current_user.id,
                    Progress.document_id == existing_document.id
                )
            )
            user_progress = progress_result.scalars().all()

            if not user_progress:
                template_result = await db.execute(
                    select(Progress)
                    .where(Progress.document_id == existing_document.id)
                    .order_by(Progress.chapter_number)
                )
                template_progress = template_result.scalars().all()
                seen_chapters = set()

                for template in template_progress:
                    if template.chapter_number in seen_chapters:
                        continue
                    seen_chapters.add(template.chapter_number)
                    db.add(Progress(
                        user_id=current_user.id,
                        document_id=existing_document.id,
                        chapter_number=template.chapter_number,
                        chapter_title=template.chapter_title or f"Chapter {template.chapter_number}",
                        status="not_started",
                        completion_percentage=0.0,
                        cognitive_level_assigned=current_user.cognitive_level,
                        time_spent_minutes=0,
                        quiz_attempts=0,
                        quiz_success_rate=0.0,
                    ))

                if not seen_chapters:
                    db.add(Progress(
                        user_id=current_user.id,
                        document_id=existing_document.id,
                        chapter_number=1,
                        chapter_title="Full document study",
                        status="not_started",
                        completion_percentage=0.0,
                        cognitive_level_assigned=current_user.cognitive_level,
                        time_spent_minutes=0,
                        quiz_attempts=0,
                        quiz_success_rate=0.0,
                    ))
                    if not existing_document.total_chapters:
                        existing_document.total_chapters = 1

                await db.commit()

            return DocumentUploadResponse(
                message="Document already exists; learning record is ready.",
                is_duplicate=True,
                document_id=existing_document.id,
                md5_hash=md5_hash,
                processing_status=existing_document.processing_status
            )

        file_type = file.filename.split(".")[-1].lower()

        # 妫€鏌ユ枃浠剁被鍨嬫槸鍚︽敮鎸?
        from app.services.document_extractors import DocumentExtractorFactory
        if not DocumentExtractorFactory.is_supported(file_type):
            supported_formats = ", ".join(DocumentExtractorFactory.supported_formats())
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"涓嶆敮鎸佺殑鏂囦欢绫诲瀷: .{file_type}銆傛敮鎸佺殑鏍煎紡: {supported_formats}"
            )

        # 鍒涘缓鏁版嵁搴撹褰曪紙蹇呴』鍦ㄥ鐞嗕箣鍓嶅垱寤猴紝浠ヤ究鑾峰彇document_id锛?
        from app.schemas.document import DocumentCreate
        document_data = DocumentCreate(
            filename=file.filename,
            file_type=file_type,
            file_size=len(content),
            md5_hash=md5_hash
        )

        new_document = await create_document(db, document_data, current_user.id)

        # 馃敡 鍒涘缓姘镐箙鏂囦欢鐩綍骞剁Щ鍔ㄦ枃浠?
        os.makedirs("uploads", exist_ok=True)
        permanent_file_path = f"uploads/{current_user.id}_{new_document.id}_{file.filename}"
        import shutil
        shutil.move(tmp_file_path, permanent_file_path)
        print(f"馃捑 鏂囦欢宸蹭繚瀛樺埌: {permanent_file_path}")

        print(f"馃摉 寮€濮嬭В鏋?{file_type} 鏂囨。...")

        # 馃攳 鏅鸿兘娣峰悎澶勭悊锛氫娇鐢?HybridDocumentProcessor
        if file_type == "pdf":
            logger.info("馃幆 妫€娴嬪埌PDF鏂囦欢锛屽皢浣跨敤HybridDocumentProcessor澶勭悊")
            try:
                from app.services.hybrid_document_processor import HybridDocumentProcessor
                from app.utils.pdf_validator import validate_pdf_before_upload

                logger.info("鉁?HybridDocumentProcessor瀵煎叆鎴愬姛")
                print(f"\n{'='*60}")
                print(f"馃敩 鏅鸿兘娣峰悎澶勭悊妯″紡")
                print(f"{'='*60}\n")

                # 棰勬娴?
                validation = validate_pdf_before_upload(permanent_file_path)

                print(f"馃搵 PDF 棰勬鏌ョ粨鏋?")
                print(f"   鎬婚〉鏁? {validation['total_pages']}")
                print(f"   鏂囨湰椤? {validation['text_pages']}")
                print(f"   鏂囨湰鍗犳瘮: {validation['text_ratio']:.1%}")
                print(f"   is scanned: {validation['is_scan']}")
                print(f"{'='*60}\n")

                # 濡傛灉鏄壂鎻忕増锛岀粰鍑烘彁绀轰絾缁х画澶勭悊锛堜笉鍐嶆嫆缁濓級
                if validation['is_scan']:
                    print(f"馃挕 妫€娴嬪埌鎵弿鐗圥DF锛屽皢浣跨敤 PaddleOCR 杩涜鏂囧瓧璇嗗埆")
                    print(f"   棰勮澶勭悊鏃堕棿: {validation['total_pages'] * 2}-{validation['total_pages'] * 5} 绉抃n")

                # 浣跨敤娣峰悎澶勭悊鍣ㄥ鐞嗘枃妗?
                processor = HybridDocumentProcessor()

                # 鏇存柊鐘舵€佷负澶勭悊涓?
                await db.execute(
                    text("UPDATE documents SET processing_status = :status WHERE id = :id"),
                    {"status": "pending", "id": new_document.id}
                )
                await db.commit()

                # 妫€鏌?OCR 骞跺彂闄愬埗
                if validation['is_scan']:
                    from app.core.ocr_semaphore import ocr_semaphore

                    task_id = f"doc_{new_document.id}"
                    acquired = await ocr_semaphore.acquire(task_id)

                    if not acquired:
                        # 妲戒綅宸叉弧锛屾帓闃熷鐞?
                        await db.execute(
                            text("UPDATE documents SET processing_status = :status WHERE id = :id"),
                            {"status": "queued", "id": new_document.id}
                        )
                        await db.commit()

                        return DocumentUploadResponse(
                            message="Document is queued. Please refresh later to check progress.",
                            is_duplicate=False,
                            document_id=new_document.id,
                            md5_hash=md5_hash,
                            processing_status="queued"
                        )

                    logger.info(f"馃攼 OCR 浠诲姟 {task_id} 鑾峰緱澶勭悊鏉冮檺")


                # 寮傛澶勭悊锛堜娇鐢?asyncio.create_task锛?
                async def process_document_async():
                    # 鍦ㄥ紓姝ヤ换鍔′腑鍒涘缓鏂扮殑鏁版嵁搴?session
                    async with async_session_maker() as async_db:
                        try:
                            result = await processor.process_document(
                                file_path=permanent_file_path,
                                document_id=new_document.id,
                                user_id=current_user.id,
                                title=title or file.filename,
                                db=async_db
                            )

                            logger.info(
                                f"鉁?鏂囨。 {new_document.id} 澶勭悊瀹屾垚: "
                                f"璺緞={result.get('path')}, "
                                f"鑰楁椂={result.get('processing_time', 0):.1f}绉? "
                                f"OCR缃俊搴?{result.get('ocr_confidence', 0):.1%}"
                            )
                            try:
                                from sqlalchemy import select, func
                                from app.models.document import Document, Progress
                                from app.services.rag_service import rebuild_document_index

                                doc_result = await async_db.execute(
                                    select(Document).where(Document.id == new_document.id)
                                )
                                indexed_document = doc_result.scalar_one_or_none()
                                if indexed_document:
                                    index_result = await rebuild_document_index(indexed_document)
                                    logger.info(
                                        f"RAG index rebuilt for document {new_document.id}: "
                                        f"{index_result.get('status')} "
                                        f"chunks={index_result.get('chunk_count', 0)}"
                                    )

                                progress_count_result = await async_db.execute(
                                    select(func.count()).select_from(Progress).where(
                                        Progress.document_id == new_document.id
                                    )
                                )
                                progress_count = progress_count_result.scalar_one()
                                if progress_count == 0:
                                    async_db.add(Progress(
                                        user_id=current_user.id,
                                        document_id=new_document.id,
                                        chapter_number=1,
                                        chapter_title="\u5168\u6587\u5b66\u4e60",
                                        status="not_started",
                                        completion_percentage=0.0,
                                        cognitive_level_assigned=current_user.cognitive_level,
                                        time_spent_minutes=0,
                                        quiz_attempts=0,
                                        quiz_success_rate=0.0,
                                    ))
                                    await async_db.execute(
                                        text(
                                            "UPDATE documents SET total_chapters = 1, "
                                            "processing_status = 'completed' WHERE id = :id"
                                        ),
                                        {"id": new_document.id},
                                    )
                                    await async_db.commit()
                            except Exception as index_error:
                                logger.error(
                                    f"Post-processing finalization failed for document "
                                    f"{new_document.id}: {index_error}",
                                    exc_info=True,
                                )


                        except Exception as e:
                            logger.error(f"鉂?鏂囨。 {new_document.id} 澶勭悊澶辫触: {e}", exc_info=True)

                            # 鏇存柊鐘舵€佷负澶辫触
                            await async_db.execute(
                                text("UPDATE documents SET processing_status = :status WHERE id = :id"),
                                {"status": "failed", "id": new_document.id}
                            )
                            await async_db.commit()

                # 鍚姩寮傛澶勭悊
                asyncio.create_task(process_document_async())

                # 绔嬪嵆杩斿洖锛岃鍓嶇鍙互杞杩涘害
                return DocumentUploadResponse(
                    message=f"鉁?鏂囨。宸蹭笂浼狅紝姝ｅ湪{'OCR璇嗗埆' if validation['is_scan'] else '澶勭悊'}涓?..",
                    is_duplicate=False,
                    document_id=new_document.id,
                    md5_hash=md5_hash,
                    processing_status="pending" if validation['is_scan'] else "processing"
                )

            except HTTPException:
                raise  # 閲嶆柊鎶涘嚭 HTTPException
            except Exception as e:
                # PDF澶勭悊澶辫触锛岃褰曢敊璇苟杩斿洖澶辫触鐘舵€?
                logger.error(f"鉂?PDF 澶勭悊澶辫触: {e}", exc_info=True)

                # 鏇存柊鐘舵€佷负澶辫触
                await db.execute(
                    text("UPDATE documents SET processing_status = :status WHERE id = :id"),
                    {"status": "failed", "id": new_document.id}
                )
                await db.commit()

                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"鏂囨。澶勭悊澶辫触: {str(e)}"
                )

        # TXT鏂囦欢澶勭悊锛氳В鏋愭枃妗ｃ€佸垏鍒嗐€佸悜閲忓寲锛堟坊鍔犺秴鏃朵繚鎶わ級
        try:
            result = await asyncio.wait_for(
                process_uploaded_document(
                    file_path=permanent_file_path,
                    title=title or file.filename,
                    user_email=current_user.email
                ),
                timeout=300.0  # 5鍒嗛挓瓒呮椂
            )
            print(f"鉁?鏂囨。瑙ｆ瀽瀹屾垚: {len(result.get('chunks', []))} 涓?chunks")
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="鏂囨。澶勭悊瓒呮椂锛堣秴杩?鍒嗛挓锛夛紝璇峰皾璇曚笂浼犺緝灏忕殑鏂囦欢"
            )

        # 馃幆 濡傛灉鏄?PDF锛屼娇鐢ㄦ櫤鑳借В鏋愬櫒鎻愬彇鐩綍锛堜功绛句紭鍏?+ 鍚彂寮忔壂鎻忥級
        toc_text = ""
        if file_type == "pdf":
            try:
                from app.core.textbook_parser import TextbookParser
                parser = TextbookParser()

                parse_result = await parser.parse_textbook(permanent_file_path, db)
                toc_text = parse_result['toc_text']

                source = parse_result['source']  # 'bookmark' or 'scan'
                pages = parse_result['pages']
                need_ai = parse_result.get('need_ai_guess', False)

                print(f"馃摎 鏅鸿兘瑙ｆ瀽瀹屾垚:")
                print(f"   鏉ユ簮: {source}")
                print(f"   椤电爜: {pages}")
                print(f"   鏂囨湰闀垮害: {len(toc_text)} 瀛楃")
                if need_ai:
                    print(f"   鈿狅笍  闇€瑕丄I杈呭姪璇嗗埆")
            except Exception as e:
                logger.warning(f"鈿狅笍  鏅鸿兘瑙ｆ瀽澶辫触: {e}锛屼娇鐢╢allback")
                toc_text = ""

        # 鍒涘缓 ChromaDB collection锛堜互 MD5 鍛藉悕锛?
        create_document_collection(md5_hash)

        # 娣诲姞 chunks 鍒?ChromaDB
        chunks = result['chunks']
        embeddings = result['embeddings']

        # 鍑嗗 metadata
        chunk_metadata = []
        for chunk in chunks:
            meta = chunk.metadata.copy()
            chunk_metadata.append(meta)

        # 鎻愬彇鏂囨湰鍐呭
        chunk_texts = [chunk.page_content for chunk in chunks]

        # 瀛樺叆 ChromaDB
        add_document_chunks(
            md5_hash=md5_hash,
            chunks=chunk_texts,
            embeddings=embeddings,
            metadata=chunk_metadata
        )

        # 鏇存柊鏂囨。鐘舵€?
        await update_document_status(
            db,
            new_document.id,
            status="completed",
            total_pages=result['stats'].get('total_pages', 0),
            total_chapters=0,  # 绋嶅悗鐢辩珷鑺傚垝鍒嗘湇鍔℃洿鏂?
            title=title or file.filename
        )

        # 馃幆 鏍稿績锛氳嚜鍔ㄥ垝鍒嗙珷鑺傦紙浣跨敤澧炲己鐗堟湇鍔★級
        try:
            # 浣跨敤澧炲己鐗堢珷鑺傚垝鍒嗘湇鍔?
            from app.services.chapter_divider_enhanced import EnhancedChapterDivider

            divider = EnhancedChapterDivider()

            # 浣跨敤澧炲己鐗堝鐞嗗櫒鎻愬彇鐨勭洰褰曟枃鏈?
            # 濡傛灉 toc_text 涓虹┖锛堟瘮濡?txt 鏂囦欢锛夛紝浣跨敤甯歌鏂囨湰
            if not toc_text:
                # 瀵逛簬闈?PDF 鎴栨彁鍙栧け璐ョ殑鎯呭喌锛屼娇鐢ㄥ墠鍑犱釜 chunks
                toc_text = "\n\n".join([c.page_content for c in chunks[:3]])

            if toc_text:
                print(f"馃摎 鍙戦€佺洰褰曟枃鏈粰 LLM锛岄暱搴? {len(toc_text)} 瀛楃")

                chapters = await divider.divide_document_into_chapters(
                    document_id=new_document.id,
                    user_id=current_user.id,
                    document_text=toc_text,  # 鍙彂閫佺洰褰曟枃鏈?
                    db=db
                )

                print(f"Document processed with {len(chapters)} chapters")

                # 鏇存柊鏂囨。鐨勭珷鑺傛暟
                await update_document_status(
                    db,
                    new_document.id,
                    status="completed",
                    total_chapters=len(chapters)
                )
            else:
                print("Could not extract TOC text; creating default chapter")
                # 鍒涘缓榛樿绔犺妭
                await create_progress(
                    db,
                    ProgressCreate(
                        user_id=current_user.id,
                        document_id=new_document.id,
                        chapter_number=1,
                        chapter_title=title or file.filename,
                        cognitive_level_assigned=current_user.cognitive_level
                    )
                )
        except Exception as e:
            print(f"鈿狅笍  绔犺妭鍒掑垎澶辫触: {str(e)}")
            import traceback
            traceback.print_exc()
            # 鍗充娇绔犺妭鍒掑垎澶辫触锛屼篃鍒涘缓涓€涓粯璁ょ珷鑺?
            await create_progress(
                db,
                ProgressCreate(
                    user_id=current_user.id,
                    document_id=new_document.id,
                    chapter_number=1,
                    chapter_title=title or file.filename,
                    cognitive_level_assigned=current_user.cognitive_level
                )
            )

        return DocumentUploadResponse(
            message=f"Document uploaded successfully: {file.filename}",
            is_duplicate=False,
            document_id=new_document.id,
            md5_hash=md5_hash,
            processing_status="completed"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"鏂囨。澶勭悊澶辫触: {str(e)}"
        )

    finally:
        # 娓呯悊涓存椂鏂囦欢锛堝彧鍒犻櫎涓存椂鏂囦欢锛屼笉鍒犻櫎姘镐箙鏂囦欢锛?
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception as e:
                # 璁板綍閿欒浣嗕笉鎶涘嚭寮傚父
                print(f"鈿狅笍  娓呯悊涓存椂鏂囦欢澶辫触: {e}")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "EduGenius API"}


@router.get("/list")
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    鑾峰彇褰撳墠鐢ㄦ埛涓婁紶鐨勬墍鏈夋枃妗ｅ垪琛?
    """
    from sqlalchemy import exists, or_, select
    from app.models.document import Document, Progress
    
    # 鏌ヨ鐢ㄦ埛鐨勬墍鏈夋枃妗?
    result = await db.execute(
        select(Document)
        .where(
            or_(
                Document.uploaded_by == current_user.id,
                exists().where(
                    (Progress.document_id == Document.id)
                    & (Progress.user_id == current_user.id)
                ),
            )
        )
        .order_by(Document.uploaded_at.desc())
    )
    documents = result.scalars().all()
    
    # 杞崲涓哄瓧鍏稿垪琛?
    document_list = []
    for doc in documents:
        document_list.append({
            "id": doc.id,
            "filename": doc.filename,
            "title": doc.title or doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "total_pages": doc.total_pages,
            "total_chapters": doc.total_chapters,
            "processing_status": doc.processing_status,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "md5_hash": doc.md5_hash
        })
    
    return {
        "documents": document_list,
        "total": len(document_list)
    }


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get document details by ID.
    """
    document = await get_document_by_md5(db, str(document_id))
    if not document:
        # Try by ID
        from app.crud.document import get_document_by_id
        document = await get_document_by_id(db, document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    return document


@router.get("/{document_id}/chapters")
async def get_document_chapters(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get chapter list with progress and lock status for a document.

    瑙ｉ攣瑙勫垯锛?
    - 绗竴绔犻粯璁よВ閿?
    - 鍚庣画绔犺妭闇€瑕佹弧瓒冲墠缃潯浠讹細
      1. 鍓嶄竴绔犲畬鎴愬害 >= 70%
      2. 鍓嶄竴绔犳祴璇曞垎鏁?>= 60%锛堝鏋滄湁娴嬭瘯璁板綍锛?
      3. 鍓嶄竴绔犲涔犳椂闂?>= 10 鍒嗛挓
    """
    from sqlalchemy import select
    from app.models.document import Document, Progress

    # 楠岃瘉鏂囨。瀛樺湪
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    document = doc_result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # 鑾峰彇鎵€鏈夎繘搴﹁褰?
    progress_result = await db.execute(
        select(Progress).where(
            Progress.user_id == current_user.id,
            Progress.document_id == document_id
        ).order_by(Progress.chapter_number)
    )
    all_progress = progress_result.scalars().all()

    if not all_progress and document.processing_status == "completed":
        fallback_progress = Progress(
            user_id=current_user.id,
            document_id=document_id,
            chapter_number=1,
            chapter_title="鍏ㄦ枃瀛︿範",
            status="not_started",
            completion_percentage=0.0,
            cognitive_level_assigned=current_user.cognitive_level,
            time_spent_minutes=0,
            quiz_attempts=0,
            quiz_success_rate=0.0,
        )
        db.add(fallback_progress)
        if not document.total_chapters:
            document.total_chapters = 1
        await db.commit()

        progress_result = await db.execute(
            select(Progress).where(
                Progress.user_id == current_user.id,
                Progress.document_id == document_id
            ).order_by(Progress.chapter_number)
        )
        all_progress = progress_result.scalars().all()

    # 鑾峰彇鎵€鏈夊皬鑺傝褰曪紙浣跨敤鍘熺敓SQL锛岄伩鍏峅RM闂锛?
    from collections import defaultdict
    from sqlalchemy import text
    subsections_by_chapter = defaultdict(list)

    try:
        subsection_query = text("""
            SELECT chapter_number, subsection_number, subsection_title,
                   page_number, completion_percentage, time_spent_minutes
            FROM subsections
            WHERE user_id = :user_id AND document_id = :document_id
            ORDER BY chapter_number, subsection_number
        """)

        result = await db.execute(
            subsection_query,
            {"user_id": current_user.id, "document_id": document_id}
        )

        rows = result.fetchall()
        for row in rows:
            subsections_by_chapter[row[0]].append({
                "subsection_number": row[1],
                "subsection_title": row[2],
                "page_number": row[3],
                "completion_percentage": row[4],
                "time_spent_minutes": row[5]
            })
    except Exception as e:
        print(f"鈿狅笍  鏃犳硶鍔犺浇灏忚妭鏁版嵁: {e}")
        # 缁х画鎵ц锛屽彧鏄笉鍖呭惈灏忚妭鏁版嵁

    # 瑙ｉ攣闃堝€奸厤缃?
    UNLOCK_CONFIG = {
        "completion_threshold": 0.7,  # 70% 瀹屾垚搴?
        "quiz_score_threshold": 0.6,  # 60% 娴嬭瘯鍒嗘暟
        "min_time_minutes": 10  # 鏈€灏?0鍒嗛挓瀛︿範鏃堕棿
    }

    chapters = []

    for progress in all_progress:
        # 鍒ゆ柇绔犺妭鐘舵€?
        is_locked = False
        lock_reason = None

        if progress.chapter_number > 1:
            # 鏌ユ壘鍓嶄竴绔犵殑杩涘害
            prev_progress = next(
                (p for p in all_progress if p.chapter_number == progress.chapter_number - 1),
                None
            )

            if prev_progress:
                # 妫€鏌ヨВ閿佹潯浠?
                conditions_met = []
                conditions_not_met = []

                # 妫€鏌ュ畬鎴愬害
                if prev_progress.completion_percentage >= UNLOCK_CONFIG["completion_threshold"] * 100:
                    conditions_met.append(f"Completion {prev_progress.completion_percentage:.0f}%")
                else:
                    conditions_not_met.append(
                        f"Previous chapter completion must reach {UNLOCK_CONFIG['completion_threshold'] * 100:.0f}% "
                        f"(current {prev_progress.completion_percentage:.0f}%)"
                    )

                # 妫€鏌ュ涔犳椂闂?
                if prev_progress.time_spent_minutes >= UNLOCK_CONFIG["min_time_minutes"]:
                    conditions_met.append(f"Study time {prev_progress.time_spent_minutes} minutes")
                else:
                    conditions_not_met.append(
                        f"Previous chapter study time must reach {UNLOCK_CONFIG['min_time_minutes']} minutes "
                        f"(current {prev_progress.time_spent_minutes} minutes)"
                    )

                # 妫€鏌ユ祴璇曞垎鏁帮紙濡傛灉鏈夋祴璇曡褰曪級
                if prev_progress.quiz_attempts > 0:
                    if prev_progress.quiz_success_rate >= UNLOCK_CONFIG["quiz_score_threshold"]:
                        conditions_met.append(f"Quiz score {prev_progress.quiz_success_rate * 100:.0f}%")
                    else:
                        conditions_not_met.append(
                            f"Previous chapter quiz score must reach {UNLOCK_CONFIG['quiz_score_threshold'] * 100:.0f}% "
                            f"(current {prev_progress.quiz_success_rate * 100:.0f}%)"
                        )

                # 濡傛灉鎵€鏈夋潯浠堕兘婊¤冻锛屽垯瑙ｉ攣
                is_locked = len(conditions_not_met) > 0

                if is_locked:
                    lock_reason = f"Complete previous chapter first: {'; '.join(conditions_not_met)}"
            else:
                # 娌℃湁鍓嶄竴绔犺褰曪紝閿佸畾
                is_locked = True
                lock_reason = "Complete the previous chapter first"

        # 濡傛灉鐘舵€佷负 locked锛屽己鍒堕攣瀹?
        if progress.status == "locked":
            is_locked = True
            lock_reason = "This chapter is locked"

        # 纭畾鐘舵€佸浘鏍?
        if is_locked:
            status_icon = "馃敀"
            status_text = "Locked"
        elif progress.status == "completed":
            status_icon = "OK"
            status_text = "Completed"
        elif progress.status == "in_progress":
            status_icon = "馃敁"
            status_text = "In progress"
        else:
            status_icon = "馃敁"
            status_text = "Not started"

        chapters.append({
            "chapter_number": progress.chapter_number,
            "chapter_title": progress.chapter_title or f"Chapter {progress.chapter_number}",
            "status": progress.status,
            "completion_percentage": progress.completion_percentage,
            "is_locked": is_locked,
            "lock_reason": lock_reason,
            "status_icon": status_icon,
            "status_text": status_text,
            "time_spent_minutes": progress.time_spent_minutes,
            "quiz_attempts": progress.quiz_attempts,
            "quiz_success_rate": progress.quiz_success_rate,
            "subsections": subsections_by_chapter.get(progress.chapter_number, []),
            "subsection_count": len(subsections_by_chapter.get(progress.chapter_number, []))
        })

    return {
        "document_id": document_id,
        "document_title": document.title or document.filename,
        "total_chapters": len(chapters),
        "chapters": chapters
    }


@router.post("/{document_id}/redivide-chapters")
async def redivide_chapters(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    閲嶆柊鍒掑垎鏂囨。绔犺妭
    浣跨敤 LLM 閲嶆柊鍒嗘瀽鏂囨。骞跺垝鍒嗙珷鑺?
    """
    from sqlalchemy import select, delete
    from app.models.document import Document, Progress
    from app.services.chapter_divider import ChapterDivider
    from app.services.document_processor import DocumentProcessor

    # 楠岃瘉鏂囨。瀛樺湪
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    document = doc_result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # 楠岃瘉鏂囨。鎵€鏈夋潈
    if document.uploaded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愭搷浣滄鏂囨。"
        )

    try:
        # 鍒犻櫎鏃х殑绔犺妭杩涘害璁板綍
        await db.execute(
            delete(Progress).where(
                Progress.user_id == current_user.id,
                Progress.document_id == document_id
            )
        )
        await db.commit()

        # 閲嶆柊瑙ｆ瀽鏂囨。
        processor = DocumentProcessor()
        result = await processor.process_document(
            file_path=None,  # 杩欓噷闇€瑕佷慨鏀癸紝搴旇浣跨敤瀛樺偍鐨勬枃浠?
            metadata={'title': document.title}
        )

        # 鑾峰彇鏂囨。鏂囨湰
        document_text = result['texts'][0] if result['texts'] else ""

        if not document_text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="鏃犳硶鎻愬彇鏂囨。鍐呭"
            )

        # 閲嶆柊鍒掑垎绔犺妭
        divider = ChapterDivider()
        chapters = await divider.divide_document_into_chapters(
            document_id=document_id,
            user_id=current_user.id,
            document_text=document_text,
            db=db
        )

        return {
            "message": f"Chapter redivision completed with {len(chapters)} chapters",
            "document_id": document_id,
            "total_chapters": len(chapters),
            "chapters": chapters
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"绔犺妭鍒掑垎澶辫触: {str(e)}"
        )


@router.get("/{document_id}/chapters/{chapter_number}/subsections")
async def get_chapter_subsections(
    document_id: int,
    chapter_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    鑾峰彇绔犺妭鐨勬墍鏈夊皬鑺?
    """
    from sqlalchemy import select, text
    from app.models.document import Progress

    print(f"\n{'='*60}")
    print(f"馃摎 API: 鑾峰彇灏忚妭鍒楄〃")
    print(f"   鐢ㄦ埛ID: {current_user.id}")
    print(f"   鏂囨。ID: {document_id}")
    print(f"   绔犺妭鍙? {chapter_number}")
    print(f"{'='*60}\n")

    # 楠岃瘉绔犺妭瀛樺湪
    progress_result = await db.execute(
        select(Progress).where(
            Progress.user_id == current_user.id,
            Progress.document_id == document_id,
            Progress.chapter_number == chapter_number
        )
    )
    progress = progress_result.scalar_one_or_none()

    if not progress:
        print(f"   鈿狅笍  绔犺妭涓嶅瓨鍦? user_id={current_user.id}, doc_id={document_id}, chapter={chapter_number}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )

    print(f"   鉁?鎵惧埌绔犺妭: {progress.chapter_title}")

    # 浣跨敤鍘熺敓SQL鏌ヨ鑾峰彇灏忚妭锛堝洜涓?Subsection 涓嶆槸鏍囧噯鐨?ORM 妯″瀷锛?
    subsections_query = text("""
        SELECT subsection_number, subsection_title, page_number,
               completion_percentage, time_spent_minutes
        FROM subsections
        WHERE user_id = :user_id
          AND document_id = :document_id
          AND chapter_number = :chapter_number
        ORDER BY subsection_number
    """)

    result = await db.execute(subsections_query, {
        "user_id": current_user.id,
        "document_id": document_id,
        "chapter_number": chapter_number
    })

    rows = result.fetchall()
    subsections = [
        {
            "subsection_number": row[0],
            "subsection_title": row[1],
            "page_number": row[2],
            "completion_percentage": row[3] or 0.0,
            "time_spent_minutes": row[4] or 0.0
        }
        for row in rows
    ]

    print(f"Found {len(subsections)} subsections")
    
    print(f"Returning {len(subsections)} subsections")

    return {
        "document_id": document_id,
        "chapter_number": chapter_number,
        "chapter_title": progress.chapter_title,
        "total_subsections": len(subsections),
        "subsections": subsections
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    鍒犻櫎鏂囨。
    """
    from sqlalchemy import select, delete
    from app.models.document import Document
    
    # 楠岃瘉鏂囨。瀛樺湪涓斿睘浜庡綋鍓嶇敤鎴?
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    if document.uploaded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愬垹闄ゆ鏂囨。"
        )
    
    # 馃敡 FIX: 绾ц仈鍒犻櫎鐩稿叧鏁版嵁
    print(f"\n{'='*60}")
    print(f"馃棏锔? 寮€濮嬪垹闄ゆ枃妗?{document_id} ({document.filename})")
    print(f"{'='*60}\n")

    from sqlalchemy import text

    # 0. 鍏堢粺璁¤鍒犻櫎鐨勬暟鎹?
    print("馃搳 缁熻瑕佸垹闄ょ殑鏁版嵁:")
    stats_check = text("""
        SELECT
            (SELECT COUNT(*) FROM conversations WHERE document_id = :doc_id AND user_id = :user_id) as conversations,
            (SELECT COUNT(*) FROM progress WHERE document_id = :doc_id AND user_id = :user_id) as progress,
            (SELECT COUNT(*) FROM subsections WHERE document_id = :doc_id AND user_id = :user_id) as subsections
    """)
    stats = await db.execute(stats_check, {
        'doc_id': document_id,
        'user_id': current_user.id
    })
    row = stats.fetchone()
    print(f"   - conversations: {row[0]}")
    print(f"   - progress: {row[1]}")
    print(f"   - subsections: {row[2]}")
    print()

    # 1. 鍒犻櫎瀵硅瘽璁板綍 (conversations 琛?
    print("馃棏锔? 姝ラ 1/6: 鍒犻櫎瀵硅瘽璁板綍...")
    conversation_delete = text("""
        DELETE FROM conversations
        WHERE document_id = :document_id AND user_id = :user_id
    """)
    result = await db.execute(conversation_delete, {
        'document_id': document_id,
        'user_id': current_user.id
    })
    conversation_count = result.rowcount
    print(f"   deleted conversations: {conversation_count}")

    # 2. 鍒犻櫎瀛︿範杩涘害璁板綍 (progress 琛? - 鍏堣幏鍙栬鍒犻櫎鐨?progress_id
    progress_ids_query = text("""
        SELECT id FROM progress
        WHERE document_id = :document_id AND user_id = :user_id
    """)
    progress_result = await db.execute(progress_ids_query, {
        'document_id': document_id,
        'user_id': current_user.id
    })
    progress_ids = [row[0] for row in progress_result.fetchall()]

    # 3. 鍒犻櫎娴嬭瘯璁板綍 (quiz_attempts 琛? - 閫氳繃 progress_id
    quiz_count = 0
    if progress_ids:
        # 鏋勫缓 IN 瀛愬彞
        placeholders = ','.join([f':pid{i}' for i in range(len(progress_ids))])
        params = {f'pid{i}': pid for i, pid in enumerate(progress_ids)}
        quiz_delete = text(f"""
            DELETE FROM quiz_attempts
            WHERE progress_id IN ({placeholders})
        """)
        quiz_result = await db.execute(quiz_delete, params)
        quiz_count = quiz_result.rowcount
        print(f"   deleted quiz attempts: {quiz_count}")

    # 鐜板湪鍒犻櫎杩涘害璁板綍
    progress_delete = text("""
        DELETE FROM progress
        WHERE document_id = :document_id AND user_id = :user_id
    """)
    result = await db.execute(progress_delete, {
        'document_id': document_id,
        'user_id': current_user.id
    })
    progress_count = result.rowcount
    print(f"   deleted progress rows: {progress_count}")

    # 4. 鍒犻櫎灏忚妭璁板綍 (subsections 琛?
    subsection_delete = text("""
        DELETE FROM subsections
        WHERE document_id = :document_id AND user_id = :user_id
    """)
    result = await db.execute(subsection_delete, {
        'document_id': document_id,
        'user_id': current_user.id
    })
    subsection_count = result.rowcount
    print(f"   deleted subsections: {subsection_count}")

    # 5. 鍒犻櫎 ChromaDB 涓殑鍚戦噺闆嗗悎
    try:
        from app.core.chroma import delete_document_collection
        deleted = delete_document_collection(document.md5_hash)
        if deleted:
            print(f"   鉁?鍒犻櫎浜?ChromaDB 鍚戦噺闆嗗悎")
        else:
            print("   ChromaDB collection does not exist")
    except Exception as e:
        print(f"   鈿狅笍  鍒犻櫎 ChromaDB 鏁版嵁澶辫触: {e}")

    # 4. 鍒犻櫎鏂囨。璁板綍
    await db.execute(
        delete(Document).where(Document.id == document_id)
    )
    await db.commit()

    print(f"\n{'='*60}")
    print(f"鉁?鏂囨。鍒犻櫎瀹屾垚")
    print(f"   鏂囨。ID: {document_id}")
    print(f"   鏂囦欢鍚? {document.filename}")
    print(f"   宸插垹闄?")
    print(f"      - conversations: {conversation_count}")
    print(f"      - quiz attempts: {quiz_count}")
    print(f"      - progress: {progress_count}")
    print(f"      - subsections: {subsection_count}")
    print(f"{'='*60}\n")

    return {
        "message": "鏂囨。鍒犻櫎鎴愬姛",
        "document_id": document_id,
        "document_title": document.title,
        "deleted_records": {
            "conversations": conversation_count,
            "quiz_attempts": quiz_count,
            "progress": progress_count,
            "subsections": subsection_count
        }
    }


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    鑾峰彇鏂囨。澶勭悊鐘舵€佸拰杩涘害

    杩斿洖璇︾粏鐨勫鐞嗚繘搴︼紝鐢ㄤ簬鍓嶇杞鏇存柊
    """
    from sqlalchemy import select, text

    # 楠岃瘉鏂囨。瀛樺湪涓斿睘浜庡綋鍓嶇敤鎴?
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if document.uploaded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯闂鏂囨。"
        )

    # 鑾峰彇澶勭悊鐘舵€?
    status_query = text("""
        SELECT
            id,
            filename,
            title,
            processing_status,
            has_text_layer,
            ocr_confidence,
            current_page,
            total_pages,
            total_chapters,
            uploaded_at
        FROM documents
        WHERE id = :document_id
    """)

    result = await db.execute(status_query, {'document_id': document_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏂囨。鐘舵€佷俊鎭笉瀛樺湪"
        )

    # 瑙ｆ瀽鐘舵€?
    status = row[3] or 'pending'
    has_text_layer = bool(row[4])
    ocr_confidence = row[5] or 0.0
    current_page = row[6] or 0
    total_pages = row[7] or 0
    total_chapters = row[8] or 0

    # 璁＄畻杩涘害鐧惧垎姣?
    progress_percentage = 0
    stage = ""
    stage_message = ""

    if status == 'pending':
        progress_percentage = 5
        stage = "绛夊緟澶勭悊"
        stage_message = "鏂囨。宸蹭笂浼狅紝姝ｅ湪鍑嗗澶勭悊..."

    elif status == 'processing':
        progress_percentage = 30
        stage = "姝ｅ湪鎻愬彇鏂囨湰"
        stage_message = "姝ｅ湪浠嶱DF涓彁鍙栨枃鏈唴瀹?.."

    elif status == 'ocr_processing':
        if total_pages > 0:
            # OCR 瀹屾垚 80%锛岀暀 20% 缁欑珷鑺傚垝鍒?
            ocr_progress = int((current_page / total_pages) * 80)
            progress_percentage = min(80, ocr_progress)
        else:
            progress_percentage = 40

        # 鏍规嵁杩涘害鏄剧ず涓嶅悓鐨勬秷鎭?
        if current_page >= total_pages and total_pages > 0:
            stage = "姝ｅ湪鍒掑垎绔犺妭"
            stage_message = "OCR 璇嗗埆瀹屾垚锛屾鍦ㄤ娇鐢?AI 鍒掑垎绔犺妭锛堢害闇€ 30 绉掞級..."
        else:
            stage = "姝ｅ湪OCR璇嗗埆"
            stage_message = f"姝ｅ湪浣跨敤 AI 璇嗗埆绗?{current_page}/{total_pages} 椤?.."

    elif status == 'completed':
        progress_percentage = 100
        stage = "澶勭悊瀹屾垚"
        stage_message = "Document processed successfully. You can start studying."

    elif status == 'failed':
        progress_percentage = 0
        stage = "澶勭悊澶辫触"
        stage_message = "鏂囨。澶勭悊澶辫触锛岃灏濊瘯閲嶆柊涓婁紶鏇存竻鏅扮殑鏂囦欢"

    # 鏋勫缓鍝嶅簲
    response = {
        "document_id": document_id,
        "filename": row[1],
        "title": row[2],
        "status": status,
        "stage": stage,
        "stage_message": stage_message,
        "progress_percentage": progress_percentage,
        "has_text_layer": has_text_layer,
        "ocr_confidence": ocr_confidence,
        "current_page": current_page,
        "total_pages": total_pages,
        "total_chapters": total_chapters,
        "is_scan": not has_text_layer,
        "uploaded_at": row[10].isoformat() if row[10] else None
    }

    # 娣诲姞鎻愮ず淇℃伅
    if status == 'completed' and not has_text_layer:
        response['warning'] = "姝ゆ枃妗ｉ€氳繃OCR璇嗗埆锛屽缓璁牳瀵逛笓涓氭湳璇拰鍏紡"
        response['ocr_notice'] = "鎵弿浠惰瘑鍒噯纭巼绾?5-95%锛岄噸瑕佸唴瀹硅鎵嬪姩鏍稿"

    return response

