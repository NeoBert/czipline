from sqlalchemy import func
import pandas as pd
from cswd.sql.base import session_scope
from cswd.sql.models import (Issue, StockDaily, Adjustment,
                             SpecialTreatment, SpecialTreatmentType)

DAILY_COLS = ['symbol', 'date',
              'open', 'high', 'low', 'close',
              'prev_close', 'change_pct',
              'volume', 'amount', 'turnover', 'cmv', 'tmv']

ADJUSTMENT_COLS = ['symbol', 'date', 'amount', 'ratio',
                   'record_date', 'pay_date', 'listing_date']


def get_exchange(code):
    if code[0] in ('0', '3'):
        return "SZSE"
    else:
        return "SSE"


def get_start_dates():
    """
    股票上市日期

    Examples
    --------
    >>> df = get_start_dates()
    >>> df.head()
    symbol  start_date
    0  000001  1991-04-03
    1  000002  1991-01-29
    2  000003  1991-01-14
    3  000004  1991-01-14
    4  000005  1990-12-10
    """
    col_names = ['symbol', 'start_date']
    with session_scope() as sess:
        query = sess.query(Issue.code, Issue.A004_上市日期).filter(
            Issue.A004_上市日期.isnot(None))
        df = pd.DataFrame.from_records(query.all())
        df.columns = col_names
        return df


def get_end_dates():
    """
    股票结束日期。限定退市或者当前处于暂停上市状态的股票

    Examples
    --------
    >>> df = get_end_dates()
    >>> df.head()
    symbol    end_date
    0  000003  2002-06-14
    1  000013  2004-09-20
    2  000015  2001-10-22
    3  000024  2015-12-30
    4  000033  2017-07-07  
    """
    col_names = ['symbol', 'end_date']
    with session_scope() as sess:
        query = sess.query(
            SpecialTreatment.code, func.max(SpecialTreatment.date)
        ).group_by(
            SpecialTreatment.code
        ).having(
            SpecialTreatment.treatment.in_(
                [SpecialTreatmentType.delisting, SpecialTreatmentType.PT]
            )
        )
        df = pd.DataFrame.from_records(query.all())
        df.columns = col_names
        return df


def gen_asset_metadata():
    """
    生成股票元数据

    Examples
    --------
    >>> df = gen_asset_metadata()
    >>> df.head()
    symbol asset_name first_traded last_traded exchange auto_close_date  \
    0  000001       平安银行   1991-01-02  2018-04-17     SZSE      2018-04-18
    1  000002       万 科Ａ   1991-01-02  2018-04-17     SZSE      2018-04-18
    2  000003      PT金田Ａ   1991-01-02  2002-04-26     SZSE      2002-04-27
    3  000004       国农科技   1991-01-02  2018-04-17     SZSE      2018-04-18
    4  000005       世纪星源   1991-01-02  2018-04-17     SZSE      2018-04-18
    start_date    end_date
    0  1991-04-03         NaN
    1  1991-01-29         NaN
    2  1991-01-14  2002-06-14
    3  1991-01-14         NaN
    4  1990-12-10         NaN      
    """
    columns = ['symbol', 'asset_name', 'first_traded', 'last_traded']
    with session_scope() as sess:
        query = sess.query(
            StockDaily.code,
            StockDaily.A001_名称,
            func.min(StockDaily.date),
            func.max(StockDaily.date)
        ).group_by(
            StockDaily.code
        )
        df = pd.DataFrame.from_records(query.all())
        df.columns = columns
        df['exchange'] = df['symbol'].map(get_exchange)
        df['auto_close_date'] = df['last_traded'].map(
            lambda x: x + pd.Timedelta(days=1))
        start_dates = get_start_dates()
        end_dates = get_end_dates()
        return df.merge(
            start_dates, 'left', on='symbol'
        ).merge(
            end_dates, 'left', on='symbol'
        )


def fetch_single_equity(stock_code, start, end):
    """
    从本地数据库读取股票期间日线交易数据

    注
    --
    1. 除OHLCV外，还包括涨跌幅、成交额、换手率、流通市值、总市值列
    2. 使用bcolz格式写入时，由于涨跌幅存在负数，必须剔除该列！！！

    Parameters
    ----------
    stock_code : str
        要获取数据的股票代码
    start_date : datetime-like
        自开始日期(包含该日)
    end_date : datetime-like
        至结束日期

    return
    ----------
    DataFrame: OHLCV列的DataFrame对象。

    Examples
    --------
    >>> symbol = '000333'
    >>> start_date = '2018-4-1'
    >>> end_date = pd.Timestamp('2018-4-16')
    >>> df = fetch_single_stock_equity(symbol, start_date, end_date)
    >>> df.iloc[:,:8]
        symbol        date   open   high    low  close  prev_close  change_pct
    0  000333  2018-04-02  53.30  55.00  52.68  52.84       54.53     -3.0992
    1  000333  2018-04-03  52.69  53.63  52.18  52.52       52.84     -0.6056
    2  000333  2018-04-04  52.82  54.10  52.06  53.01       52.52      0.9330
    3  000333  2018-04-09  52.91  53.31  51.00  51.30       53.01     -3.2258
    4  000333  2018-04-10  51.45  52.80  51.18  52.77       51.30      2.8655
    5  000333  2018-04-11  52.78  53.63  52.41  52.98       52.77      0.3980
    6  000333  2018-04-12  52.91  52.94  51.84  51.87       52.98     -2.0951
    7  000333  2018-04-13  52.40  52.47  51.01  51.32       51.87     -1.0603
    8  000333  2018-04-16  51.31  51.80  49.15  49.79       51.32     -2.9813    
    """
    start = pd.Timestamp(start).date()
    end = pd.Timestamp(end).date()
    with session_scope() as sess:
        query = sess.query(StockDaily.code,
                           StockDaily.date,
                           StockDaily.A002_开盘价,
                           StockDaily.A003_最高价,
                           StockDaily.A004_最低价,
                           StockDaily.A005_收盘价,
                           StockDaily.A009_前收盘,
                           StockDaily.A011_涨跌幅,
                           StockDaily.A006_成交量,
                           StockDaily.A007_成交金额,
                           StockDaily.A008_换手率,
                           StockDaily.A013_流通市值,
                           StockDaily.A012_总市值)
        query = query.filter(StockDaily.code == stock_code
                             ).filter(StockDaily.date.between(start, end))
        df = pd.DataFrame.from_records(query.all())
        df.columns = DAILY_COLS
        return df


def fetch_single_quity_adjustments(stock_code, start, end):
    """
    从本地数据库读取股票期间分红派息数据

    Parameters
    ----------
    stock_code : str
        要获取数据的股票代码
    start : datetime-like
        自开始日期
    end : datetime-like
        至结束日期

    return
    ----------
    DataFrame对象

    Examples
    --------
    >>> fetch_single_quity_adjustments('600000', '2010-4-1', '2018-4-16')
        symbol        date  amount  ratio record_date    pay_date listing_date
    0  600000  2010-06-10   0.150    0.3  2010-06-09  2010-06-11   2010-06-10
    1  600000  2011-06-03   0.160    0.3  2011-06-02  2011-06-07   2011-06-03
    2  600000  2012-06-26   0.300    0.0  2012-06-25  2012-06-26   2012-06-26
    3  600000  2013-06-03   0.550    0.0  2013-05-31  2013-06-03   2013-06-03
    4  600000  2014-06-24   0.660    0.0  2014-06-23  2014-06-24   2014-06-24
    5  600000  2015-06-23   0.757    0.0  2015-06-19  2015-06-23   2015-06-23
    6  600000  2016-06-23   0.515    0.1  2016-06-22  2016-06-24   2016-06-23
    7  600000  2017-05-25   0.200    0.3  2017-05-24  2017-05-26   2017-05-25
    """
    start = pd.Timestamp(start).date()
    end = pd.Timestamp(end).date()
    with session_scope() as sess:
        query = sess.query(Adjustment.code,
                           Adjustment.date,
                           Adjustment.A002_派息,
                           Adjustment.A003_送股,
                           Adjustment.A004_股权登记日,
                           Adjustment.A005_除权基准日,
                           Adjustment.A006_红股上市日)
        query = query.filter(Adjustment.code == stock_code)
        query = query.filter(Adjustment.date.between(start, end))
        df = pd.DataFrame.from_records(query.all())
        if df.empty:
            # 返回一个空表
            return df
        df.columns = ADJUSTMENT_COLS
        return df