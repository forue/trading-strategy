export const CAL_DATE_FONT = 'Manrope, sans-serif'
export const CAL_TEXT_FONT = 'system-ui, "Microsoft YaHei", sans-serif'

/** 卡片底色：格子间隙、边框以及 calendar 底层格子都用它，避免圆角缺口露出杂色 */
export function calendarSurfaceColor(isDark: boolean) {
  return isDark ? '#17171A' : '#FFFFFF'
}

/** 两个日历共用的格子样式：边框融进卡片底色，圆角与间隙对所有系列一致 */
export function calendarItemStyle(isDark: boolean, mobile: boolean) {
  return {
    borderColor: calendarSurfaceColor(isDark),
    // 边框色融进卡片底色，靠它拉格子间隙：桌面 3px 更松弛，手机 2px 保留内容区
    borderWidth: mobile ? 2 : 3,
    borderRadius: mobile ? 5 : 7,
  }
}

/** 悬停高亮：用主题强调色，明显区别于任何底色，避免悬停后仍贴近背景 */
export function calendarEmphasisItemStyle(isDark: boolean) {
  return {
    color: isDark ? '#7B93F5' : '#4051E0',
    borderColor: isDark ? '#E8EAF0' : '#FFFFFF',
    borderWidth: 2,
    shadowBlur: 10,
    shadowColor: isDark ? 'rgba(0,0,0,0.55)' : 'rgba(0,0,0,0.22)',
  }
}

/**
 * 两个日历共用的三档底色与对应文字色：本月交易日(无数据) > 本月休市 > 非本月。
 * 统一这些颜色避免两页观感不一致；有数据时的强调色由各业务自行决定。
 */
export function calendarCellPalette(isDark: boolean) {
  return {
    neutral: isDark ? '#454B58' : '#D7DBE2',
    closed: isDark ? '#2C303A' : '#EAECF0',
    outside: isDark ? '#1B1D23' : '#F7F7F8',
    neutralDate: isDark ? '#ECEFF5' : '#3F444D',
    closedDate: isDark ? '#9297A5' : '#9499A2',
    outsideDate: isDark ? '#5F6470' : '#C7CAD1',
    neutralSub: isDark ? '#B4BAC7' : '#5C626C',
    closedSub: isDark ? '#7F8492' : '#9A9EA6',
    outsideSub: isDark ? '#5F6470' : '#C7CAD1',
    axisText: isDark ? '#9DA1B0' : '#71717A',
  }
}

/** 共用标签样式：日期数字用 Manrope 加粗，第二行状态/收益用中文系统字体常规字重 */
export function calendarLabelBase(
  isDark: boolean,
  mobile: boolean,
  rich: Record<string, { color: string }> = {},
) {
  return {
    show: true,
    position: 'inside' as const,
    align: 'center' as const,
    verticalAlign: 'middle' as const,
    fontFamily: CAL_DATE_FONT,
    fontWeight: 700 as const,
    fontSize: mobile ? 12 : 13,
    lineHeight: mobile ? 14 : 16,
    color: isDark ? '#F0F1F5' : '#20232B',
    rich: Object.fromEntries(Object.entries(rich).map(([key, style]) => [key, {
      fontFamily: CAL_TEXT_FONT,
      fontWeight: 400 as const,
      fontSize: mobile ? 9 : 10,
      lineHeight: 13,
      ...style,
    }])),
    // 悬停时日期放大加粗，第二行同步放大，两行文字都转白以贴合高亮底色
    emphasis: {
      fontSize: mobile ? 15 : 17,
      fontWeight: 700 as const,
      color: '#FFFFFF',
      rich: Object.fromEntries(Object.keys(rich).map(key => [key, {
        fontFamily: CAL_TEXT_FONT,
        fontSize: mobile ? 11 : 12,
        fontWeight: 700 as const,
        color: '#FFFFFF',
      }])),
    },
  }
}
