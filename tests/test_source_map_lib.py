"""验证Source Map库API的测试 - 实现前必须运行"""

import json
import sourcemap


def test_sourcemap_library_api():
    """验证Source Map库的实际API（实现前必须运行）"""
    # 测试用的简单Source Map
    source_map_content = {
        "version": 3,
        "sources": ["src/app.js"],
        "sourcesContent": ["const x = 1;\nconst y = 2;\nconst z = 3;"],
        "names": ["x", "y", "z"],
        "mappings": "AAAA,MAAM,CAAC,GAAG,CAAC"
    }
    
    # 验证解析API
    sm = sourcemap.loads(json.dumps(source_map_content))
    
    # 验证lookup API和返回值结构
    token = sm.lookup(line=0, column=0)
    print(f"Token type: {type(token)}")
    print(f"Token structure: {dir(token)}")
    
    if token:
        print(f"Token.src: {getattr(token, 'src', 'NO ATTR')}")
        print(f"Token.src_line: {getattr(token, 'src_line', 'NO ATTR')}")
        print(f"Token.src_col: {getattr(token, 'src_col', 'NO ATTR')}")
        print(f"Token.name: {getattr(token, 'name', 'NO ATTR')}")
    
    # 验证SourceMap结构
    print(f"\nSourceMap type: {type(sm)}")
    print(f"SourceMap structure: {dir(sm)}")
    
    # 检查源码内容访问方式
    if hasattr(sm, 'sourcesContent'):
        print(f"Has sourcesContent: {sm.sourcesContent}")
    elif hasattr(sm, 'sources_content'):
        print(f"Has sources_content: {sm.sources_content}")
    elif hasattr(sm, 'get_sources_content'):
        print(f"Has get_sources_content(): {sm.get_sources_content()}")
    else:
        print("No direct source content access found")
        
    # 检查sources属性
    if hasattr(sm, 'sources'):
        print(f"Sources: {sm.sources}")
    
    # 检查raw属性中的sourcesContent
    if hasattr(sm, 'raw'):
        print(f"\nRaw type: {type(sm.raw)}")
        if isinstance(sm.raw, dict) and 'sourcesContent' in sm.raw:
            print(f"Raw sourcesContent: {sm.raw['sourcesContent']}")
        
    return sm, token


if __name__ == "__main__":
    sm, token = test_sourcemap_library_api()