# 리트리버 MCP 테스트 시나리오

1. 데이터셋 생성: create_dataset(name='test_ds') 호출
2. 문서 업로드: upload_document(dataset_id='test_ds', file_path='test_doc_1.txt', use_hierarchical='true', metadata={'type':'manual'}) 호출
3. 검색 테스트: search(query='FastAPI', dataset_ids=['test_ds'], fusion='rrf') 호출
4. 데이터 정리: delete_dataset(dataset_id='test_ds') 호출
