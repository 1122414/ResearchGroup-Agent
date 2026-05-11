from fastapi import APIRouter, HTTPException

from ..core.logger import logger
from ..storage.repositories import OutputRepository

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


@router.get("")
async def get_outputs(run_id: str | None = None):
    logger.debug("[API] get_outputs | run_id=%s", run_id)
    if run_id:
        outputs = OutputRepository.get_by_run(run_id)
    else:
        outputs = []
    return {"outputs": outputs}


@router.get("/{output_id}")
async def get_output(output_id: str):
    logger.debug("[API] get_output | output_id=%s", output_id)
    output = OutputRepository.get_by_id(output_id)
    if not output:
        logger.warning("[API] get_output | output_id=%s not found", output_id)
        raise HTTPException(status_code=404, detail="产出不存在")
    return {"output": output}
