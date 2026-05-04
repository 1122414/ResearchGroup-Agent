from fastapi import APIRouter, HTTPException
from ..storage.repositories import OutputRepository

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


@router.get("")
async def get_outputs(run_id: str | None = None):
    if run_id:
        outputs = OutputRepository.get_by_run(run_id)
    else:
        outputs = []
    return {"outputs": outputs}


@router.get("/{output_id}")
async def get_output(output_id: str):
    output = OutputRepository.get_by_id(output_id)
    if not output:
        raise HTTPException(status_code=404, detail="产出不存在")
    return {"output": output}
