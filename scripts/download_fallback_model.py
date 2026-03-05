#!/usr/bin/env python3
"""
Qwen3 Fallback 모델 다운로드/검증 스크립트

사용법:
    python scripts/download_fallback_model.py              # 모델 다운로드
    python scripts/download_fallback_model.py --verify     # 다운로드 + 검증 (추론 테스트)
    python scripts/download_fallback_model.py --status     # 현재 상태 확인만
    python scripts/download_fallback_model.py --unload     # 캐시 정리

M4 Pro Apple Silicon 환경에서 MPS 가속을 사용한다.
모델: Qwen/Qwen2.5-7B-Instruct (~14GB)
예상 다운로드 시간: 네트워크 속도에 따라 5~20분
예상 메모리 사용: float16 로드 시 ~14GB
"""

from __future__ import annotations

import argparse
import gc
import shutil
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"


def check_dependencies() -> bool:
    """필수 패키지 설치 여부를 확인한다."""
    missing = []

    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")

    try:
        import transformers  # noqa: F401
    except ImportError:
        missing.append("transformers")

    if missing:
        print(f"[ERROR] 필수 패키지 미설치: {', '.join(missing)}")
        print()
        print("설치 방법:")
        print("  pip install torch transformers accelerate")
        print()
        print("Apple Silicon MPS 가속을 위해 PyTorch nightly 권장:")
        print("  pip install --pre torch --index-url https://download.pytorch.org/whl/nightly/cpu")
        return False

    return True


def get_device_info() -> dict:
    """디바이스 정보를 반환한다."""
    import torch

    info = {
        "torch_version": torch.__version__,
        "mps_available": torch.backends.mps.is_available(),
        "mps_built": torch.backends.mps.is_built(),
        "cuda_available": torch.cuda.is_available(),
        "device": "cpu",
    }

    if info["mps_available"]:
        info["device"] = "mps"
    elif info["cuda_available"]:
        info["device"] = "cuda"

    return info


def get_cache_info() -> dict:
    """HuggingFace 캐시 정보를 반환한다."""
    from transformers import AutoModelForCausalLM

    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"

    # 모델이 이미 캐시에 있는지 확인
    model_cache_pattern = MODEL_NAME.replace("/", "--")
    cached_dirs = list(cache_dir.glob(f"models--{model_cache_pattern}*"))

    total_size = 0
    if cached_dirs:
        for d in cached_dirs:
            for f in d.rglob("*"):
                if f.is_file():
                    total_size += f.stat().st_size

    return {
        "cache_dir": str(cache_dir),
        "model_cached": len(cached_dirs) > 0,
        "cache_size_gb": round(total_size / (1024 ** 3), 2),
        "cached_dirs": [str(d) for d in cached_dirs],
    }


def show_status() -> None:
    """현재 상태를 출력한다."""
    print("=" * 60)
    print(f"  Fallback 모델 상태: {MODEL_NAME}")
    print("=" * 60)
    print()

    if not check_dependencies():
        return

    device_info = get_device_info()
    print("[디바이스 정보]")
    print(f"  PyTorch 버전: {device_info['torch_version']}")
    print(f"  MPS 사용 가능: {device_info['mps_available']}")
    print(f"  MPS 빌드됨: {device_info['mps_built']}")
    print(f"  CUDA 사용 가능: {device_info['cuda_available']}")
    print(f"  사용할 디바이스: {device_info['device']}")
    print()

    cache_info = get_cache_info()
    print("[캐시 정보]")
    print(f"  캐시 디렉토리: {cache_info['cache_dir']}")
    print(f"  모델 캐시됨: {cache_info['model_cached']}")
    print(f"  캐시 크기: {cache_info['cache_size_gb']} GB")
    print()

    if cache_info["model_cached"]:
        print("[결과] 모델이 이미 다운로드되어 있습니다.")
    else:
        print("[결과] 모델이 다운로드되어 있지 않습니다.")
        print("  다운로드: python scripts/download_fallback_model.py")


def download_model() -> bool:
    """모델과 토크나이저를 다운로드한다."""
    print(f"[INFO] 모델 다운로드 시작: {MODEL_NAME}")
    print("[INFO] 최초 다운로드는 네트워크 속도에 따라 5~20분 소요될 수 있습니다.")
    print()

    from transformers import AutoModelForCausalLM, AutoTokenizer

    start = time.monotonic()

    # 1. 토크나이저 다운로드
    print("[1/2] 토크나이저 다운로드 중...")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
    )
    print(f"  토크나이저 다운로드 완료 (vocab_size={tokenizer.vocab_size})")

    # 2. 모델 다운로드 (float16)
    print("[2/2] 모델 다운로드 중 (~14GB)...")
    import torch

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        trust_remote_code=True,
    )
    param_count = sum(p.numel() for p in model.parameters()) / 1e9
    print(f"  모델 다운로드 완료 (parameters={param_count:.1f}B)")

    elapsed = time.monotonic() - start
    print()
    print(f"[SUCCESS] 다운로드 완료 (소요 시간: {elapsed:.0f}초)")

    # 메모리 정리
    del model
    del tokenizer
    gc.collect()

    return True


def verify_model() -> bool:
    """모델을 로드하고 간단한 추론 테스트를 수행한다."""
    print()
    print("[INFO] 모델 검증 시작 (로드 + 추론 테스트)")
    print()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device_info = get_device_info()
    device = device_info["device"]

    # 1. 토크나이저 로드
    print("[1/3] 토크나이저 로드 중...")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
    )
    print("  토크나이저 로드 완료")

    # 2. 모델 로드
    print(f"[2/3] 모델 로드 중 (device={device})...")
    start = time.monotonic()

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map="auto" if device != "mps" else None,
        trust_remote_code=True,
    )

    if device == "mps":
        model = model.to(device)

    model.eval()
    load_time = time.monotonic() - start
    print(f"  모델 로드 완료 (소요: {load_time:.1f}초)")

    # 3. 추론 테스트
    print("[3/3] 추론 테스트 중...")
    test_prompt = (
        "You are a financial analyst. Given the following market data, "
        "provide a brief JSON response with fields: action (buy/sell/hold), "
        "ticker, confidence (0.0-1.0), reason.\n\n"
        "Market data: S&P 500 up 1.2%, VIX at 15.3, AAPL earnings beat expectations.\n\n"
        "Respond in JSON only:"
    )

    messages = [{"role": "user", "content": test_prompt}]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(text, return_tensors="pt").to(device)

    start = time.monotonic()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            temperature=0.3,
            do_sample=True,
            top_p=0.9,
        )

    input_length = inputs["input_ids"].shape[1]
    generated_ids = outputs[0][input_length:]
    response = tokenizer.decode(generated_ids, skip_special_tokens=True)

    gen_time = time.monotonic() - start
    token_count = len(generated_ids)
    tokens_per_sec = token_count / gen_time if gen_time > 0 else 0

    print(f"  생성 완료 (tokens={token_count}, {tokens_per_sec:.1f} tok/s, {gen_time:.1f}초)")
    print()
    print("  [생성 결과]")
    for line in response.strip().split("\n"):
        print(f"    {line}")

    # 메모리 정리
    del model
    del tokenizer
    gc.collect()
    if device == "mps":
        torch.mps.empty_cache()
    elif device == "cuda":
        torch.cuda.empty_cache()

    print()
    print("[SUCCESS] 모델 검증 완료. Fallback 시스템 사용 준비 완료.")
    return True


def clear_cache() -> None:
    """모델 캐시를 정리한다."""
    cache_info = get_cache_info()
    if not cache_info["model_cached"]:
        print("[INFO] 캐시에 모델이 없습니다.")
        return

    print(f"[INFO] 캐시 크기: {cache_info['cache_size_gb']} GB")
    print(f"[INFO] 캐시 디렉토리: {cache_info['cached_dirs']}")

    confirm = input("캐시를 삭제하시겠습니까? (y/N): ").strip().lower()
    if confirm != "y":
        print("[INFO] 취소되었습니다.")
        return

    for d in cache_info["cached_dirs"]:
        shutil.rmtree(d, ignore_errors=True)
        print(f"  삭제됨: {d}")

    print("[SUCCESS] 캐시 정리 완료")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qwen3 Fallback 모델 다운로드/검증 스크립트"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="다운로드 후 추론 테스트까지 수행",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="현재 상태 확인만 수행",
    )
    parser.add_argument(
        "--unload",
        action="store_true",
        help="모델 캐시 정리",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.unload:
        if not check_dependencies():
            sys.exit(1)
        clear_cache()
        return

    if not check_dependencies():
        sys.exit(1)

    show_status()
    print()

    cache_info = get_cache_info()
    if cache_info["model_cached"]:
        print("[INFO] 모델이 이미 캐시에 있습니다. 다운로드를 건너뜁니다.")
    else:
        if not download_model():
            sys.exit(1)

    if args.verify:
        if not verify_model():
            sys.exit(1)

    print()
    print("=" * 60)
    print("  완료. src/fallback/ 모듈에서 이 모델을 자동으로 로드합니다.")
    print("=" * 60)


if __name__ == "__main__":
    main()
