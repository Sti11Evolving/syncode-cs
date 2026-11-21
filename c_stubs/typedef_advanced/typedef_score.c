typedef unsigned int Count;
typedef Count Rating;
typedef Rating Score;

Rating average_score(Score values[], Count length);

int main(void)
{
    Score values[] = {5, 3, 8, 2, 7};
    Count length = 5;
    Rating average;

    average = average_score(values, length);

    return 0;
}

// Return the integer average of the score array.
Rating average_score(Score values[], Count length)
{
