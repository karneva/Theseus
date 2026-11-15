import { describe, expect, it, vi } from 'vitest';
import { parseStructuredPlanJson } from './structuredPlan';

describe('parseStructuredPlanJson', () => {
  it('빈 값, 배열/원시 JSON, blocks/tasks가 없는 객체는 null', () => {
    expect(parseStructuredPlanJson(null)).toBeNull();
    expect(parseStructuredPlanJson('')).toBeNull();
    expect(parseStructuredPlanJson('[1,2]')).toBeNull();
    expect(parseStructuredPlanJson('"text"')).toBeNull();
    expect(parseStructuredPlanJson('{"goal":"x"}')).toBeNull();
  });

  it('깨진 JSON은 경고만 남기고 null', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    expect(parseStructuredPlanJson('{not json', 'Test')).toBeNull();
    expect(warn).toHaveBeenCalledWith(
      '[Test] Failed to parse structuredPlanJson:',
      expect.any(SyntaxError),
    );
  });

  it('blocks 형식: id/title fallback과 version을 정규화한다', () => {
    const plan = parseStructuredPlanJson(
      JSON.stringify({
        planVersion: 3,
        blocks: [
          { blockId: 'b1', title: 'First', content: 'hello' },
          { id: 7, name: 'Second', content: ['a', 'b'] },
          'raw text',
        ],
      }),
    );

    expect(plan?.version).toBe(3);
    expect(plan?.blocks).toEqual([
      { blockId: 'b1', title: 'First', content: 'hello' },
      { blockId: '7', title: 'Second', content: '- a\n- b' },
      { blockId: 'block-3', title: 'Block 3', content: 'raw text' },
    ]);
  });

  it('tasks 형식: snake/camel 키를 모두 읽어 field와 feedbackTarget을 만든다', () => {
    const plan = parseStructuredPlanJson(
      JSON.stringify({
        version: '2',
        tasks: [
          {
            id: 'T1',
            title: 'Collect metrics',
            problem: '  no metrics  ',
            expectedEffect: 'visibility',
            target_files: ['a.py', 'b.py'],
            parentId: 'root',
            tier: 'core',
          },
        ],
      }),
    );

    expect(plan?.version).toBe('2');
    const block = plan?.blocks[0];
    expect(block).toMatchObject({
      blockId: 'T1',
      title: 'Collect metrics',
      parentId: 'root',
      tier: 'core',
      status: null,
    });
    expect(block?.fields).toEqual([
      { fieldId: 'problem', label: 'Problem', value: 'no metrics', feedbackTarget: 'T1.problem' },
      {
        fieldId: 'expected_effect',
        label: 'Expected effect',
        value: 'visibility',
        feedbackTarget: 'T1.expected_effect',
      },
      {
        fieldId: 'target_files',
        label: 'Target files',
        value: '- a.py\n- b.py',
        feedbackTarget: 'T1.target_files',
      },
    ]);
    expect(block?.content).toBe(
      'Problem\nno metrics\n\nExpected effect\nvisibility\n\nTarget files\n- a.py\n- b.py',
    );
  });

  it('알려진 필드가 없는 task는 JSON 전체를 본문으로 보여 준다', () => {
    const plan = parseStructuredPlanJson(JSON.stringify({ tasks: [{ foo: 'bar' }] }));

    expect(plan?.version).toBe(1);
    expect(plan?.blocks[0]).toMatchObject({
      blockId: 'task-1',
      title: 'Task 1',
      content: JSON.stringify({ foo: 'bar' }, null, 2),
      fields: [],
    });
  });

  it('개요/보완 필요/검증 기준 섹션을 순서대로 만든다', () => {
    const plan = parseStructuredPlanJson(
      JSON.stringify({
        goal: 'Ship it',
        context: { problem_analysis: 'slow' },
        execution_spec_validation: { warnings: ['missing tests'] },
        verification: { success_criteria: 'p95 < 1s', test_commands: ['pytest'] },
        tasks: [],
      }),
    );

    expect(plan?.sections).toEqual([
      { sectionId: 'overview', title: '개요', content: '목표\nShip it\n\n문제 분석\nslow' },
      {
        sectionId: 'validation-warnings',
        title: '보완 필요',
        content: '- missing tests',
        tone: 'warning',
      },
      {
        sectionId: 'verification',
        title: '검증 기준',
        content: '성공 기준\np95 < 1s\n\n테스트 명령\n- pytest',
      },
    ]);
  });
});
