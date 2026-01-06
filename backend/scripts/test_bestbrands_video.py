#!/usr/bin/env python3
"""
Test script for Best Brands video feature
Usage: python scripts/test_bestbrands_video.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bestbrands_video import (
    detect_bestbrands_trigger,
    get_stored_file_id,
    store_file_id,
    BEST_BRANDS_VIDEO_PATH,
    BESTBRANDS_TEXT_FALLBACK
)


def test_trigger_detection():
    """Test trigger detection for various phrases"""
    print("=" * 60)
    print("TRIGGER DETECTION TESTS")
    print("=" * 60)
    
    should_trigger = [
        ("розкажи про best brands", "UA + EN company name"),
        ("що таке best brands", "UA question + EN name"),
        ("розкажи про бест брендс", "UA + transliterated name"),
        ("tell me about best brands", "EN question + name"),
        ("про компанію", "UA company question"),
        ("about best brands", "EN about + name"),
        ("what is avtd", "EN question + AVTD"),
        ("розкажи про компанію best brands", "UA + EN code-switch"),
        ("Best Brands?", "Simple question mark"),
        ("про best brands", "UA про + EN name"),
        ("о компании", "RU company question"),
        ("расскажи о best brands", "RU question + EN name"),
        ("about the company", "EN company question"),
    ]
    
    should_not_trigger = [
        ("хто ви", "Maya personality - UA"),
        ("who are you", "Maya personality - EN"),
        ("кто вы", "Maya personality - RU"),
        ("best practice", "False positive - best practice"),
        ("brands we carry", "False positive - brands"),
        ("про вас", "About Maya, not company"),
        ("tell me about yourself", "Maya personality - EN"),
        ("hello maya", "Greeting"),
        ("який коктейль", "Random question"),
        ("greenday vodka", "Product question"),
    ]
    
    passed = 0
    failed = 0
    
    print("\n--- Should TRIGGER video ---")
    for phrase, description in should_trigger:
        result = detect_bestbrands_trigger(phrase)
        if result:
            print(f"  ✅ PASS: \"{phrase}\" ({description})")
            passed += 1
        else:
            print(f"  ❌ FAIL: \"{phrase}\" ({description}) - Expected True, got False")
            failed += 1
    
    print("\n--- Should NOT trigger video ---")
    for phrase, description in should_not_trigger:
        result = detect_bestbrands_trigger(phrase)
        if not result:
            print(f"  ✅ PASS: \"{phrase}\" ({description})")
            passed += 1
        else:
            print(f"  ❌ FAIL: \"{phrase}\" ({description}) - Expected False, got True")
            failed += 1
    
    print(f"\n📊 Trigger Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_video_file():
    """Test video file exists and is valid"""
    print("\n" + "=" * 60)
    print("VIDEO FILE TESTS")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    if os.path.exists(BEST_BRANDS_VIDEO_PATH):
        print(f"  ✅ PASS: Video file exists at {BEST_BRANDS_VIDEO_PATH}")
        passed += 1
        
        size_mb = os.path.getsize(BEST_BRANDS_VIDEO_PATH) / (1024 * 1024)
        print(f"  📦 File size: {size_mb:.2f} MB")
        
        if size_mb < 50:
            print(f"  ✅ PASS: Size under Telegram 50MB limit")
            passed += 1
        else:
            print(f"  ❌ FAIL: File too large for Telegram (>50MB)")
            failed += 1
    else:
        print(f"  ❌ FAIL: Video file not found at {BEST_BRANDS_VIDEO_PATH}")
        failed += 1
    
    print(f"\n📊 Video File Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_text_fallback():
    """Test text fallback content"""
    print("\n" + "=" * 60)
    print("TEXT FALLBACK TESTS")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    if BESTBRANDS_TEXT_FALLBACK:
        print(f"  ✅ PASS: Fallback text defined ({len(BESTBRANDS_TEXT_FALLBACK)} chars)")
        passed += 1
    else:
        print(f"  ❌ FAIL: Fallback text is empty")
        failed += 1
    
    required_content = [
        "Best Brands",
        "GreenDay",
        "Dovbush",
        "avtd.com",
    ]
    
    for content in required_content:
        if content in BESTBRANDS_TEXT_FALLBACK:
            print(f"  ✅ PASS: Contains '{content}'")
            passed += 1
        else:
            print(f"  ❌ FAIL: Missing '{content}'")
            failed += 1
    
    print(f"\n📊 Text Fallback Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_file_id_caching():
    """Test file_id storage and retrieval"""
    print("\n" + "=" * 60)
    print("FILE_ID CACHING TESTS")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    try:
        test_file_id = "TEST_FILE_ID_12345"
        
        result = store_file_id(test_file_id)
        if result:
            print(f"  ✅ PASS: Stored test file_id")
            passed += 1
        else:
            print(f"  ❌ FAIL: Failed to store file_id")
            failed += 1
            return False
        
        retrieved = get_stored_file_id()
        if retrieved == test_file_id:
            print(f"  ✅ PASS: Retrieved correct file_id")
            passed += 1
        else:
            print(f"  ❌ FAIL: Retrieved '{retrieved}' instead of '{test_file_id}'")
            failed += 1
        
        new_file_id = "NEW_FILE_ID_67890"
        store_file_id(new_file_id)
        retrieved = get_stored_file_id()
        if retrieved == new_file_id:
            print(f"  ✅ PASS: Updated file_id correctly")
            passed += 1
        else:
            print(f"  ❌ FAIL: File_id update failed")
            failed += 1
            
    except Exception as e:
        print(f"  ❌ FAIL: Exception during caching test: {e}")
        failed += 1
    
    print(f"\n📊 File_ID Caching Tests: {passed} passed, {failed} failed")
    return failed == 0


def test_case_insensitivity():
    """Test that triggers work regardless of case"""
    print("\n" + "=" * 60)
    print("CASE INSENSITIVITY TESTS")
    print("=" * 60)
    
    test_cases = [
        "BEST BRANDS",
        "Best Brands",
        "best brands",
        "РОЗКАЖИ ПРО BEST BRANDS",
        "Tell Me About Best Brands",
    ]
    
    passed = 0
    failed = 0
    
    for phrase in test_cases:
        result = detect_bestbrands_trigger(phrase)
        if result:
            print(f"  ✅ PASS: \"{phrase}\"")
            passed += 1
        else:
            print(f"  ❌ FAIL: \"{phrase}\" - Case sensitivity issue")
            failed += 1
    
    print(f"\n📊 Case Insensitivity Tests: {passed} passed, {failed} failed")
    return failed == 0


def run_all_tests():
    """Run all test suites"""
    print("\n" + "=" * 60)
    print("BEST BRANDS VIDEO FEATURE - TEST SUITE")
    print("=" * 60)
    
    results = []
    
    results.append(("Trigger Detection", test_trigger_detection()))
    results.append(("Video File", test_video_file()))
    results.append(("Text Fallback", test_text_fallback()))
    results.append(("File_ID Caching", test_file_id_caching()))
    results.append(("Case Insensitivity", test_case_insensitivity()))
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️  SOME TESTS FAILED - Review above for details")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
